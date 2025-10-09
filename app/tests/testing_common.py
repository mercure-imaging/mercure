"""
testing_common.py
=================
"""
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import common  # noqa: F401
import docker.errors
import process  # noqa: F401
import pydicom
import routing  # noqa: F401
from docker.types import Mount
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import generate_uid
from tests.getdcmtags import process_dicom

pydicom.config.settings.reading_validation_mode = pydicom.config.IGNORE
pydicom.config.settings.writing_validation_mode = pydicom.config.IGNORE

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
    def __init__(self) -> None:
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

    def __init__(self) -> None:
        pass

    def pull(self, etc):
        pass


def make_fake_processor(fs, mocked, fails) -> Callable:
    def fake_processor(tag, *, environment: Optional[Dict] = None, volumes: Optional[Dict] = None, mounts: List[Mount] = [], **kwargs):
        global processor_path
        if "cat" in kwargs.get("command", ""):
            raise docker.errors.ContainerError(None, None, None, None, None)
        if tag == "busybox:stable-musl":
            return mocked.DEFAULT
        if not volumes and not mounts:
            raise Exception("No volume specified")
        in_ = Path(next(m for m in mounts if m["Target"] == "/tmp/data")['Source'])
        out_ = Path(next(m for m in mounts if m["Target"] == "/tmp/output")['Source'])

        assert in_.exists()
        assert out_.exists()

        # in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
        # out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

        # processor_path = in_.parent
        for child in in_.iterdir():
            print(f"FAKE PROCESSOR: Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)
        with (in_ / "task.json").open("r") as fp:
            results = json.load(fp)["process"]["settings"].get("result", {})
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
    if output_filename:
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)

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


def mock_incoming_uid(config, fs, series_uid, tags={}, name="bar", force_tags_output=None) -> Tuple[str, str]:
    incoming = Path(config.incoming_folder)
    dcm_file = incoming / f"{name}.dcm"
    create_minimal_dicom(dcm_file, series_uid, tags)
    dcm_file = process_dicom(str(dcm_file), "0.0.0.0", "mercure", "mercure") or Path()
    tags_f = str(dcm_file).replace('.dcm', '.tags')

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

def fake_check_output(command, encoding="utf-8", stderr=None, **opts) -> str:
    result_file = Path(command[-1])
    dummy_sent_file = """Detailed Report on the Transfer of Instances
                        ============================================

                        Communication Peer : 127.0.0.1:4242
                        AE Titles used     : DCMSEND -> ORTHANC
                        Current Date/Time  : 2025-07-25 18:53:23

                        Number        : 1
                        Filename      : one.dcm
                        SOP Instance  : 1.3.6.7.8.9
                        SOP Class     : 1.2.3.4.5 = CTImageStorage
                        Original Xfer : 1.2.840 = Little Endian Explicit
                        Dataset Size  : 527438 bytes
                        Association   : 1
                        Pres. Context : 1
                        Network Xfer  : 1.2.840 = Little Endian Explicit
                        DIMSE Status  : 0x0000 (Success)

                        Status Summary
                        --------------
                        Number of associations   : 1
                        Number of pres. contexts : 1
                        Number of SOP instances  : 1
                          - sent to the peer       : 1
                          * with status SUCCESS  : 1 """
    # Note: number of spaces is important as parsing is done line by line.
    dummy_sent_file = dummy_sent_file.replace("                        ", "")
    try:
        result_file.write_text(dummy_sent_file)
    except Exception as e:
        print(f"Error writing to {result_file}: {e}")
        raise
    return "Success"