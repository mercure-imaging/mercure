"""
test_processor.py
==============
"""
import shutil
from pytest_mock import MockerFixture

import process.process_series
import router

import processor

import json
from pprint import pprint
from common.types import *
import routing
import routing.generate_taskfile
from pathlib import Path

from testing_common import load_config
from docker.models.containers import ContainerCollection

from nomad.api.job import Job

config_partial = {
    "modules": {
        "test_module": {
            "url": "",
            "docker_tag": "busybox:stable",
            "additional_volumes": "",
            "environment": "",
            "docker_arguments": "",
        }
    },
    "rules": {
        "catchall": {
            "rule": "True",
            "target": "test_target",
            "disabled": "False",
            "fallback": "False",
            "contact": "",
            "comment": "",
            "tags": "",
            "action": "process",
            "action_trigger": "series",
            "study_trigger_condition": "timeout",
            "study_trigger_series": "",
            "priority": "normal",
            "processing_module": "test_module",
            "processing_settings": "",
            "notification_webhook": "",
            "notification_payload": "",
            "notification_trigger_reception": "False",
            "notification_trigger_completion": "False",
            "notification_trigger_error": "False",
        }
    },
}


def create_and_route(fs, mocker, uid="TESTFAKEUID"):
    mocker.patch(
        "routing.route_series.push_series_serieslevel", new=mocker.spy(routing.route_series, "push_series_serieslevel")
    )
    mocker.patch(
        "routing.route_series.push_serieslevel_outgoing",
        new=mocker.spy(routing.route_series, "push_serieslevel_outgoing"),
    )
    mocker.patch(
        "routing.generate_taskfile.create_series_task", new=mocker.spy(routing.generate_taskfile, "create_series_task")
    )
    mocker.patch("router.route_series", new=mocker.spy(router, "route_series"))
    #mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})

    fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

    router.run_router()

    router.route_series.assert_called_once_with(uid)
    routing.route_series.push_series_serieslevel.assert_called_once_with({"catchall": True}, [f"{uid}#bar"], uid, {})
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(
        {"catchall": True}, [f"{uid}#bar"], uid, {}, {}
    )

    processor_path = next(Path("/var/processing").iterdir())
    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
        k.name for k in Path("/var/processing").glob("**/*") if k.is_file()
    ]

    mocker.patch("processor.process_series", new=mocker.spy(process.process_series, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"]


def test_process_series_nomad(fs, mocker: MockerFixture):
    load_config(
        fs, {"process_runner": "nomad", **config_partial},
    )

    files = create_and_route(fs, mocker)

    processor_path = next(Path("/var/processing").iterdir())

    def fake_processor(tag=None, meta=None):
        in_ = processor_path / "in"
        out_ = processor_path / "out"
        # print(f"Processing {processor_path}")
        for child in in_.iterdir():
            # print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)
        return {
            "DispatchedJobID": "mercure-processor/dispatch-1624378734-e8388181",
            "EvalID": "f2fd681b-bc41-50cc-3d15-79f2f5c661e2",
            "EvalCreateIndex": 1138,
            "JobCreateIndex": 1137,
            "Index": 1138,
        }

    fake_run = mocker.Mock(return_value=b"", side_effect=fake_processor)
    mocker.patch.object(Job, "dispatch_job", new=fake_run)
    mocker.patch.object(Job, "get_job", new=lambda x, y: dict(Status="dead"))

    processor.run_processor()
    process.process_series.process_series.assert_called_once_with(str(processor_path))

    fake_run.assert_called_once_with(
        "mercure-processor", meta={"IMAGE_ID": "busybox:stable", "PATH": processor_path.name}
    )

    for k in Path("/var/processing").rglob("*"):
        print(k)
    for k in Path("/var/success").rglob("*"):
        print(k)

    # (processor_path / ".complete").touch()
    # processor.run_processor()

    assert (Path("/var/success") / processor_path.name).exists()
    assert files == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]
    with open(Path("/var/success") / processor_path.name / "task.json") as t:
        task = json.load(t)
    assert task == {
        "info": {
            "uid": "TESTFAKEUID",
            "uid_type": "series",
            "triggered_rules": "catchall",
            "mrn": "MISSING",
            "acc": "MISSING",
            "mercure_version": "0.2a",
            "mercure_appliance": "master",
            "mercure_server": "nomad",
        },
        "dispatch": {},
        "process": {
            "url": "",
            "docker_tag": "busybox:stable",
            "additional_volumes": "",
            "environment": "",
            "docker_arguments": "",
        },
        "study": {},
        "nomad_info": {
            "DispatchedJobID": "mercure-processor/dispatch-1624378734-e8388181",
            "EvalID": "f2fd681b-bc41-50cc-3d15-79f2f5c661e2",
            "EvalCreateIndex": 1138,
            "JobCreateIndex": 1137,
            "Index": 1138,
        },
    }

    fs.create_file(f"/var/incoming/FAILEDFAILED#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/FAILEDFAILED#bar.tags", contents="{}")

    def process_failed(self, tag, meta):
        return {
            "DispatchedJobID": "mercure-processor/dispatch-1234567898-12345678",
            "EvalID": "f2fd681b-bc41-50cc-3d15-79f2f5c661e2",
            "EvalCreateIndex": 1138,
            "JobCreateIndex": 1137,
            "Index": 1138,
        }

    mocker.patch.object(Job, "dispatch_job", new=process_failed)

    router.run_router()
    processor_path = next(Path("/var/processing").iterdir())
    processor.run_processor()

    assert (Path("/var/error") / processor_path.name).exists()
    assert ["task.json", "FAILEDFAILED#bar.dcm", "FAILEDFAILED#bar.tags"] == [
        k.name for k in (Path("/var/error") / processor_path.name / "in").rglob("*") if k.is_file()
    ]
    assert ["task.json"] == [
        k.name for k in (Path("/var/error") / processor_path.name / "out").rglob("*") if k.is_file()
    ]


def test_process_series(fs, mocker: MockerFixture):
    global processor_path
    load_config(
        fs, {"process_runner": "docker", **config_partial},
    )

    files = create_and_route(fs, mocker)
    processor_path = None

    def fake_processor(tag, environment, volumes: Dict):
        global processor_path
        in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/data")))
        out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/output")))

        processor_path = in_.parent
        for child in in_.iterdir():
            print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)

    fake_run = mocker.Mock(return_value=b"", side_effect=fake_processor)

    mocker.patch.object(ContainerCollection, "run", new=fake_run)

    processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    process.process_series.process_series.assert_called_once_with(str(processor_path))

    fake_run.assert_called_once_with(
        "busybox:stable",
        environment={},
        volumes={
            str(processor_path / "in"): {"bind": "/data", "mode": "rw"},
            str(processor_path / "out"): {"bind": "/output", "mode": "rw"},
        },
    )

    assert [] == [k.name for k in Path("/var/processing").glob("**/*")]

    assert files == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]
