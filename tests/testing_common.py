"""
testing_common.py
=================
"""
import json
import os
from pathlib import Path
import shutil
from typing import Callable, Dict, Any, Iterator, Optional

import pytest
import process
import routing, common, router, processor
import common.config as config
from common.types import Config
import docker.errors

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
            "router.route_series",
            "router.route_studies",
            "process.process_series",
            "common.monitor.post",
            "common.monitor.send_event",
            "common.monitor.send_register_series",
            "common.monitor.send_register_task",
            "common.monitor.send_task_event",
            "common.monitor.async_send_task_event",
            "common.monitor.send_processor_output",
            "common.monitor.send_update_task",
            "common.notification.trigger_notification_for_rule"
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


@pytest.fixture(scope="function", autouse=True)
def mercure_config(fs) -> Callable[[Dict], Config]:
    # TODO: config from previous calls seems to leak in here
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/data/test_config.json")

    fs.add_real_file(config_path, target_path=config.configuration_filename, read_only=False)
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing"]:
        fs.create_dir(f"/var/{k}")

    def set_config(extra: Dict[Any, Any] = {}) -> Config:
        config.read_config()
        config.mercure = Config(**{**config.mercure.dict(), **extra})  #   # type: ignore
        print(config.mercure.targets)
        config.save_config()
        return config.mercure

    set_config()
    return set_config


def mock_task_ids(mocker, task_id, next_task_id) -> None:
    def generate_uuids() -> Iterator[str]:
        yield from [task_id, next_task_id]

    generator = generate_uuids()
    mocker.patch("uuid.uuid1", new=lambda: next(generator))


class FakeDockerContainer:
    def __init__(self):
        pass

    def wait(self):
        return {"StatusCode": 0}

    def logs(self):
        test_string = "Log output"
        return test_string.encode(encoding="utf8")

    def remove(self):
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