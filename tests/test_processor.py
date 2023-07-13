"""
test_processor.py
==============
"""
from typing import Tuple
import os
import shutil
import unittest
from unittest.mock import call
import uuid
from pytest_mock import MockerFixture
import common
from common.monitor import task_event

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

from testing_common import *

from docker.models.containers import ContainerCollection

from nomad.api.job import Job
from nomad.api.jobs import Jobs
import socket

logger = config.get_logger()

processor_path = Path()
config_partial: Dict[str, Dict] = {
    "modules": {
        "test_module": Module(docker_tag="busybox:stable",settings={"fizz":"buzz"}).dict(),
    },
    "rules": {
        "catchall": Rule(
            rule="True",
            action="process",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    },
}

expected_task_info = {
            "uid": "TESTFAKEUID",
            "action": "process",
            "applied_rule": "catchall",
            "uid_type": "series",
            "triggered_rules": {"catchall": True},
            "patient_name": "MISSING",
            "mrn": "MISSING",
            "acc": "MISSING",
            "mercure_version": mercure_version.get_version_string(),
            "mercure_appliance": "master",
            "mercure_server": socket.gethostname(),
        }

def create_and_route(fs, mocked, task_id, uid="TESTFAKEUID") -> Tuple[List[str], str]:
    print("Mocked task_id is", task_id)

    new_task_id = "new-task-" + str(uuid.uuid1())

    mock_task_ids(mocked, task_id, new_task_id)
    # mocked.patch("routing.route_series.parse_ascconv", new=lambda x: {})

    fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

    router.run_router()

    router.route_series.assert_called_once_with(task_id, uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, {})  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, {}, {})  # type: ignore

    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
        k.name for k in Path("/var/processing").glob("**/*") if k.is_file()
    ]

    mocked.patch("processor.process_series", new=mocked.spy(processor, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"], new_task_id


@pytest.mark.asyncio
async def test_process_series_nomad(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    mercure_config(
        {"process_runner": "nomad", **config_partial},
    )
    fs.create_file(f"nomad/mercure-processor-template.nomad", contents="foo")
    mocked.patch.object(Jobs, "parse", new=lambda x, y: {})

    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id)

    processor_path = next(Path("/var/processing").iterdir())

    def fake_processor(tag=None, meta=None, do_process=True, **kwargs):
        in_ = processor_path / "in"
        out_ = processor_path / "out"
        # print(f"Processing {processor_path}")
        for child in in_.iterdir():
            # print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)
        return unittest.mock.DEFAULT

    fake_run = mocked.Mock(
        side_effect=fake_processor,
        return_value={
            "DispatchedJobID": "mercure-processor/dispatch-1624378734-e8388181",
            "EvalID": "f2fd681b-bc41-50cc-3d15-79f2f5c661e2",
            "EvalCreateIndex": 1138,
            "JobCreateIndex": 1137,
            "Index": 1138,
        },
    )
    mocked.patch.object(Job, "register_job", new=lambda *args: None)
    mocked.patch.object(Job, "dispatch_job", new=fake_run)
    mocked.patch.object(Job, "get_job", new=lambda x, y: dict(Status="dead"))

    logger.info("Run processing...")
    await processor.run_processor()
    processor.process_series.assert_called_once_with(processor_path)  # type: ignore

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
        "id": new_task_id,
        "info": expected_task_info,
        "dispatch": {},
        "process": {
            "module_name": "test_module",
            "module_config": {"constraints": "", "resources": "", **config_partial["modules"]["test_module"]},
            "settings": {"fizz":"buzz"},
            "retain_input_images": False,
        },
        "study": {},
        "nomad_info": fake_run.return_value,
    }

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}/", "Moved files"),
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job dispatched"),
            call(task_event.PROCESS_COMPLETE, new_task_id, 1, "", "Processing complete"),
            call(task_event.COMPLETE, new_task_id, 0, "", "Task complete"),
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

    mock_task_ids(mocked, task_id, new_task_id)

    router.run_router()
    processor_path = next(Path("/var/processing").iterdir())
    await processor.run_processor()

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
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}/", "Moved files"),
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job dispatched"),
            call(task_event.ERROR, new_task_id, 0, "", "Processing failed"),
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


@pytest.mark.asyncio
async def test_process_series(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    global processor_path
    config = mercure_config(
        {"process_runner": "docker", **config_partial},
    )
    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id)
    processor_path = Path()

    def fake_processor(tag, environment, volumes: Dict, **kwargs):
        global processor_path
        in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
        out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

        processor_path = in_.parent
        for child in in_.iterdir():
            print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)

        return mocked.DEFAULT

    fake_run = mocked.Mock(return_value=my_fake_container(), side_effect=fake_processor)  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    await processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    # process.process_series.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    uid_string = f"{os.getuid()}:{os.getegid()}"
    fake_run.assert_called_once_with(
        config.modules["test_module"].docker_tag,
        environment={"MERCURE_IN_DIR": "/tmp/data", "MERCURE_OUT_DIR": "/tmp/output"},
        user=uid_string,
        group_add=[os.getegid()],
        volumes={
            str(processor_path / "in"): {"bind": "/tmp/data", "mode": "rw"},
            str(processor_path / "out"): {"bind": "/tmp/output", "mode": "rw"},
        },
        detach=True,
    )

    assert [] == [k.name for k in Path("/var/processing").glob("**/*")]
    assert files == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}/", "Moved files"),
            call(task_event.PROCESS_COMPLETE, new_task_id, 1, "", "Processing job complete"),
            call(task_event.COMPLETE, new_task_id, 0, "", "Task complete"),
        ]
    )
    common.monitor.async_send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job running"),
        ]
    )



@pytest.mark.asyncio
async def test_multi_process_series(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    global processor_path
    partial: Dict[str, Dict] = {
        "modules": {
            "test_module_1": Module(docker_tag="busybox:stable",settings={"fizz":"buzz","result":{"value":[1,2,3,4]}}).dict(),
            "test_module_2": Module(docker_tag="busybox:stable",settings={"fizz":"bing","result":{"value":[100,200,300,400]}}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="process",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module=["test_module_1","test_module_2"],
                processing_settings=[{"foo":"bar"},{"bar":"baz"}],
                processing_retain_images=True
            ).dict()
        },
    }
    config = mercure_config(
        {"process_runner": "docker", **partial},
    )
    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id)
    processor_path = Path()

    def fake_processor(tag, environment, volumes: Dict, **kwargs):
        global processor_path
        in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
        out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

        processor_path = in_.parent
        for child in in_.iterdir():
            print(f"Moving {child} to {out_ / child.name})")
            shutil.copy(child, out_ / child.name)
        with (in_ / "task.json").open("r") as fp:
            results = json.load(fp)["process"]["settings"]["result"]
        fs.create_file(out_ / "result.json", contents=json.dumps(results))
        return mocked.DEFAULT

    fake_run = mocked.Mock(return_value=my_fake_container(), side_effect=fake_processor)  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    await processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    # process.process_series.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    uid_string = f"{os.getuid()}:{os.getegid()}"
    fake_run.assert_has_calls(
        [call(
            config.modules[m].docker_tag,
            environment={"MERCURE_IN_DIR": "/tmp/data", "MERCURE_OUT_DIR": "/tmp/output"},
            user=uid_string,
            group_add=[os.getegid()],
            volumes={
                str(processor_path / "in"): {"bind": "/tmp/data", "mode": "rw"},
                str(processor_path / "out"): {"bind": "/tmp/output", "mode": "rw"},
            },
            detach=True,
            )
            for m in partial["rules"]["catchall"]["processing_module"]
        ]
    )

    assert [] == [k.name for k in Path("/var/processing").glob("**/*")]
    assert [*files, 'result.json'] == [k.name for k in (Path("/var/success") / processor_path.name).glob("*") if k.is_file()]

    with open(Path("/var/success") / processor_path.name / "task.json") as t:
        task = json.load(t)
    
    assert task == {
        "id": new_task_id,
        "info": expected_task_info,
        "dispatch": {},
        "process": [{
            "module_name": m,
            "module_config": {"constraints": "", "resources": "", **partial["modules"][m]},
            "settings": { **partial["modules"][m]["settings"],**partial["rules"]["catchall"]["processing_settings"][i]},
            "retain_input_images": True,
        } for i, m in enumerate(partial["modules"])],
        "study": {},
        "nomad_info": None,
    }
    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}/", "Moved files"),
            call(task_event.PROCESS_COMPLETE, new_task_id, 1, "", "Processing job complete"),
            call(task_event.COMPLETE, new_task_id, 0, "", "Task complete"),
        ]
    )
    common.monitor.async_send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module_1", "Processing job running"),
            call(task_event.PROCESS_MODULE_BEGIN, new_task_id, 1, "test_module_1", "Processing module running"),
            call(task_event.PROCESS_MODULE_COMPLETE, new_task_id, 1, "test_module_1", "Processing module complete"),
            call(task_event.PROCESS_MODULE_BEGIN, new_task_id, 1, "test_module_2", "Processing module running"),
            call(task_event.PROCESS_MODULE_COMPLETE, new_task_id, 1, "test_module_2", "Processing module complete"),
        ]
    )
    common.monitor.send_processor_output.assert_has_calls(  # type: ignore
        [
            call(Task(**task),TaskProcessing(**task["process"][i]),i, partial["modules"][m]["settings"]["result"]) for i,m in enumerate(partial["modules"])
        ]
    )
