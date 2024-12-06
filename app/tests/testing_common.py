"""
testing_common.py
=================
"""
import json
import os
from pathlib import Path
import shutil
import socket
from typing import Callable, Dict, Any, Iterator, List, Optional, Tuple
import uuid

import pydicom
pydicom.config.settings.reading_validation_mode = pydicom.config.IGNORE
pydicom.config.settings.writing_validation_mode = pydicom.config.IGNORE


from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid

import pytest
import routing, common, process, bookkeeping
import common.config as config
from common.types import Config
import docker.errors

from tests.getdcmtags import process_dicom


def spy_on(mocker, obj) -> None:
    pieces = obj.split(".")
    module = ".".join(pieces[0:-1])
    mocker.patch(obj, new=mocker.spy(eval(module), pieces[-1]))


def spies(mocker, list_of_spies) -> None:
    for spy in list_of_spies:
        spy_on(mocker, spy)


def attach_spies(mocker) -> None:
    spies(
        mocker,
        [
            "routing.route_series.push_series_serieslevel",
            "routing.route_series.push_serieslevel_outgoing",
            "routing.route_studies.route_study",
            "routing.generate_taskfile.create_series_task",
            "routing.route_studies.move_study_folder",
            "routing.route_studies.push_studylevel_error",
            "routing.generate_taskfile.create_study_task",
            "routing.router.route_series",
            "routing.router.route_studies",
            "process.processor.process_series",
            # "process.process_series",
            "common.monitor.post",
            "common.monitor.send_event",
            "common.monitor.send_register_series",
            "common.monitor.send_register_task",
            "common.monitor.send_task_event",
            "common.monitor.async_send_task_event",
            "common.monitor.send_processor_output",
            "common.monitor.send_update_task",
            "common.notification.trigger_notification_for_rule",
            "common.notification.send_email",
            "uuid.uuid1"
        ],
    )
    # mocker.patch("processor.process_series", new=mocker.spy(process.process_series, "process_series"))

    # spy_on(mocker, "routing.route_series.push_series_serieslevel")
    # # mocker.patch(
    # #     "routing.route_series.push_series_serieslevel", new=mocker.spy(routing.route_series, "push_series_serieslevel")
    # # )
    # mocker.patch(
    #     "routing.route_series.push_serieslevel_outgoing",
    #     new=mocker.spy(routing.route_series, "push_serieslevel_outgoing"),
    # )
    # mocker.patch(
    #     "routing.generate_taskfile.create_series_task", new=mocker.spy(routing.generate_taskfile, "create_series_task")
    # )

    # mocker.patch("common.monitor.post", new=mocker.spy(common.monitor, "post"))
    # mocker.patch("common.monitor.send_register_series", new=mocker.spy(common.monitor, "send_register_series"))
    # mocker.patch("common.monitor.send_register_task", new=mocker.spy(common.monitor, "send_register_task"))
    # mocker.patch("common.monitor.send_event", new=mocker.spy(common.monitor, "send_event"))
    # mocker.patch("common.monitor.send_task_event", new=mocker.spy(common.monitor, "send_task_event"))
    # mocker.patch("router.route_series", new=mocker.spy(router, "route_series"))
    # mocker.patch("processor.process_series", new=mocker.spy(process.process_series, "process_series"))


@pytest.fixture(scope="function")
def mocked(mocker):
    mocker.resetall()
    attach_spies(mocker)
    return mocker

@pytest.fixture(scope="module")
def bookkeeper_port():
    return random_port()


@pytest.fixture(scope="function", autouse=True)
def mercure_config(fs, bookkeeper_port) -> Callable[[Dict], Config]:
    # TODO: config from previous calls seems to leak in here
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/data/test_config.json")

    fs.add_real_file(config_path, target_path=config.configuration_filename, read_only=False)
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing", "jobs"]:
        fs.create_dir(f"/var/{k}")

    def set_config(extra: Dict[Any, Any] = {}) -> Config:
        config.read_config()
        config.mercure = Config(**{**config.mercure.dict(), **extra})  #   # type: ignore
        print(config.mercure.targets)
        config.save_config()
        return config.mercure

    # set_config()
    set_config({"bookkeeper": "sqlite:///tmp/mercure_bookkeeper_"+str(uuid.uuid4())+".db"}) # sqlite3 is not inside the fakefs so this is going to be a real file

    bookkeeper_env = f"""PORT={bookkeeper_port}
HOST=0.0.0.0
DATABASE_URL={config.mercure.bookkeeper}"""
    fs.create_file(bookkeeping.bookkeeper.bk_config.config_filename, contents=bookkeeper_env)

    fs.add_real_directory(os.path.abspath(os.path.dirname(os.path.realpath(__file__))+'/../alembic'))
    fs.add_real_file(os.path.abspath(os.path.dirname(os.path.realpath(__file__))+'/../alembic.ini'),read_only=True)
    return set_config


def mock_task_ids(mocker, task_id, next_task_id) -> None:
    if not isinstance(next_task_id, list):
        next_task_id = [next_task_id]
    real_uuid = uuid.uuid1
    def generate_uuids() -> Iterator[str]:
        yield from [task_id] + next_task_id
        while True:
            yield str(real_uuid())
    generator = generate_uuids()
    
    mocker.patch("uuid.uuid1", new=lambda: next(generator))


class FakeDockerContainer:
    def __init__(self):
        pass

    def wait(self):
        return {"StatusCode": 0}

    def logs(self, **kwargs):
        test_string = "Log output"
        return test_string.encode(encoding="utf8")

    def remove(self):
        pass

class FakeImageContainer:
    attrs: Any = {}
    def __init__(self):
        pass
    def pull(self, etc):
        pass

def make_fake_processor(fs, mocked, fails):
    def fake_processor(tag, environment: Optional[Dict] = None, volumes: Optional[Dict] = None, **kwargs):
        global processor_path
        if "cat" in kwargs.get("command",""):
            raise docker.errors.ContainerError(None,None,None,None,None)
        if tag == "busybox:stable-musl":
            return mocked.DEFAULT
        if not volumes:
            raise Exception()
        in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
        out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

        # processor_path = in_.parent
        for child in in_.iterdir():
            print(f"FAKE PROCESSOR: Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)
        with (in_ / "task.json").open("r") as fp:
            results = json.load(fp)["process"]["settings"].get("result",{})
        fs.create_file(out_ / "result.json", contents=json.dumps(results))
        if fails:
            raise Exception("failed")
        return mocked.DEFAULT
    return fake_processor


def create_minimal_dicom(output_filename, series_uid, additional_tags=None) -> Dataset:
    """
    Create a minimal DICOM file with the given series UID and additional tags.
    
    :param output_filename: The filename to save the DICOM file
    :param series_uid: The Series Instance UID to use
    :param additional_tags: A dictionary of additional DICOM tags and their values
    :return: None
    """
    if not series_uid:
        series_uid = generate_uid()
    # Create a new DICOM dataset
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage  # Raw Data Storage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.ImplementationClassUID = generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian  # Implicit VR Little Endian transfer syntax

    # Create the FileDataset instance
    ds = FileDataset(output_filename, {}, file_meta=file_meta, preamble=b"\0" * 128)

    # Add the minimal required data elements
    ds.StudyInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    # Add additional tags
    if additional_tags:
        for tag, value in additional_tags.items():
            setattr(ds, tag, value)
    ds.SeriesInstanceUID = series_uid

    # Save the DICOM file
    if output_filename:
        ds.save_as(output_filename)
        print(f"Minimal DICOM file saved: {output_filename}")
    return ds


def mock_incoming_uid(config, fs, series_uid, tags={}, name="bar", force_tags_output=None) -> Tuple[str,str]:    
    incoming = Path(config.incoming_folder)
    dcm_file = incoming / f"{name}.dcm"
    create_minimal_dicom(dcm_file, series_uid, tags)
    dcm_file = process_dicom(str(dcm_file), "0.0.0.0","mercure","mercure")
    tags_f = str(dcm_file).replace('.dcm','.tags')

    # print("@@@@@@@", dcm_file, tags_f)
    # print("$$$$$$$" + Path(tags_f).read_text())
    # dcm_file = fs.create_file(incoming / series_uid / f"{series_uid}#{name}.dcm", contents="asdfasdfafd")
    # tags_f = fs.create_file(incoming / series_uid / f"{series_uid}#{name}.tags", contents=json.dumps(tags))
    # print("@@@@@@@", dcm_file, tags_f)


    if force_tags_output is not None:
        with open(tags_f, 'wb') as f:
            if isinstance(force_tags_output, str):
                f.write(force_tags_output.encode())
            else:
                f.write(force_tags_output)

    # ( incoming / "receiver_info").mkdir(exist_ok=True)
    # ( incoming / "receiver_info" / (series_uid+".received")).touch()
    return str(dcm_file), tags_f

def random_port() -> int:
    """
    Generate a free port number to use as an ephemeral endpoint.
    """
    s = socket.socket() 
    s.bind(('',0)) # bind to any available port
    port = s.getsockname()[1] # get the port number
    s.close()
    return int(port)


@pytest.fixture(scope="module")
def receiver_port():
    return random_port()
