"""
test_processor.py
==============
"""
import os
import shutil
from unittest.mock import call
import uuid
from pytest_mock import MockerFixture
import common

import process.process_series
import router
import daiquiri
import processor
from common.constants import mercure_version

import json
from pprint import pprint
from common.types import *
import routing
import routing.generate_taskfile
from pathlib import Path

from testing_common import load_config, mocked
from docker.models.containers import ContainerCollection

from nomad.api.job import Job
from nomad.api.jobs import Jobs
import socket

logger = daiquiri.getLogger("test_processor")

processor_path = Path()
config_partial = {
    "modules": {
        "test_module": {
            "docker_tag": "busybox:stable",
            "additional_volumes": "",
            "environment": "",
            "docker_arguments": "",
            "settings": {},
            "contact": "",
            "comment": "",
        }
    },
    "rules": {
        "catchall": {
            "rule": "True",
            # "target": "test_target",
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
            "processing_retain_images": "False",
            "notification_webhook": "",
            "notification_payload": "",
            "notification_trigger_reception": "False",
            "notification_trigger_completion": "False",
            "notification_trigger_error": "False",
        }
    },
}


def create_and_route(fs, mocked, task_id, uid="TESTFAKEUID") -> List[str]:
    mocked.patch("uuid.uuid1", new=lambda: task_id)
    # mocked.patch("routing.route_series.parse_ascconv", new=lambda x: {})

    fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

    router.run_router()

    router.route_series.assert_called_once_with(task_id, uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, {})  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, {}, {})  # type: ignore

    processor_path = next(Path("/var/processing").iterdir())
    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
        k.name for k in Path("/var/processing").glob("**/*") if k.is_file()
    ]

    mocked.patch("processor.process_series", new=mocked.spy(processor, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"]


def test_process_series_nomad(fs, mocked: MockerFixture):
    load_config(
        fs,
        {"process_runner": "nomad", **config_partial},
    )
    fs.create_file(f"nomad/mercure-processor-template.nomad", contents="foo")
    mocked.patch.object(Jobs, "parse", new=lambda x, y: {})

    task_id = str(uuid.uuid1())
    files = create_and_route(fs, mocked, task_id)

    processor_path = next(Path("/var/processing").iterdir())

    def fake_processor(tag=None, meta=None, **kwargs):
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

    fake_run = mocked.Mock(return_value=b"", side_effect=fake_processor)
    mocked.patch.object(Job, "register_job", new=lambda *args: None)
    mocked.patch.object(Job, "dispatch_job", new=fake_run)
    mocked.patch.object(Job, "get_job", new=lambda x, y: dict(Status="dead"))

    logger.info("Run processing...")
    processor.run_processor()
    processor.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    fake_run.assert_called_once_with("processor-test_module", meta={"PATH": processor_path.name})

    for k in Path("/var/processing").rglob("*"):
        logger.info(k)
    for k in Path("/var/success").rglob("*"):
        logger.info(k)
    # (processor_path / ".complete").touch(exist_ok=False)
    # processor.run_processor()

    assert (Path("/var/success") / processor_path.name).exists(), f"{processor_path.name} missing from success dir"
    assert files == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]
    with open(Path("/var/success") / processor_path.name / "task.json") as t:
        task = json.load(t)
    assert task == {
        "id": task_id,
        "info": {
            "uid": "TESTFAKEUID",
            "action": "process",
            "applied_rule": "catchall",
            "uid_type": "series",
            "triggered_rules": {"catchall": True},
            "mrn": "MISSING",
            "acc": "MISSING",
            "mercure_version": mercure_version.get_version_string(),
            "mercure_appliance": "master",
            "mercure_server": socket.gethostname(),
        },
        "dispatch": {},
        "process": {
            "module_name": "test_module",
            "module_config": {
                "docker_tag": "busybox:stable",
                "additional_volumes": "",
                "environment": "",
                "constraints": "",
                "resources": "",
                "docker_arguments": "",
                "settings": {},
                "contact": "",
                "comment": "",
            },
            "settings": {},
            "retain_input_images": "False",
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

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call("REGISTERED", task_id, 1, "", "Registered series"),
            call("UNKNOWN", task_id, 0, "", "Processing job dispatched."),
            call("UNKNOWN", task_id, 0, "", "Processing complete"),
            call("COMPLETE", task_id, 0, "", "Task complete"),
        ]
    )
    common.monitor.send_task_event.reset_mock()  # type: ignore

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

    mocked.patch.object(Job, "dispatch_job", new=process_failed)

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
    print(common.monitor.send_event.call_args_list)  # type: ignore

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call("REGISTERED", task_id, 1, "", "Registered series"),
            call("UNKNOWN", task_id, 0, "", "Processing job dispatched."),
            call("ERROR", task_id, 0, "", "Processing failed"),
        ]
    )


class my_fake_container:
    def __init__(self):
        pass

    def wait(self):
        return {"StatusCode": 0}

    def logs(self):
        test_string = "Log output"
        return test_string.encode(encoding="utf8")

    def remove(self):
        pass


def test_process_series(fs, mocked: MockerFixture):
    global processor_path
    load_config(
        fs,
        {"process_runner": "docker", **config_partial},
    )
    task_id = str(uuid.uuid1())
    files = create_and_route(fs, mocked, task_id)
    processor_path = Path()

    def fake_processor(tag, environment, volumes: Dict, **kwargs):
        global processor_path
        in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/data")))
        out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/output")))

        processor_path = in_.parent
        for child in in_.iterdir():
            print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)

        return mocked.DEFAULT

    fake_run = mocked.Mock(return_value=my_fake_container(), side_effect=fake_processor)  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    # process.process_series.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    uid_string = f"{os.getuid()}:{os.getegid()}"
    fake_run.assert_called_once_with(
        "busybox:stable",
        environment={"MERCURE_IN_DIR": "/data", "MERCURE_OUT_DIR": "/output"},
        user=uid_string,
        group_add=[os.getegid()],
        volumes={
            str(processor_path / "in"): {"bind": "/data", "mode": "rw"},
            str(processor_path / "out"): {"bind": "/output", "mode": "rw"},
        },
        detach=True,
    )

    assert [] == [k.name for k in Path("/var/processing").glob("**/*")]
    assert files == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call("REGISTERED", task_id, 1, "", "Registered series"),
            call("UNKNOWN", task_id, 0, "test_module", "Processing job running."),
            call("UNKNOWN", task_id, 0, "", "Processing job complete"),
            call("COMPLETE", task_id, 0, "", "Task complete"),
        ]
    )
