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

import router
import processor
from itertools import permutations
from common.constants import mercure_version, mercure_names

import json
from common.types import *
import routing
import routing.generate_taskfile
from pathlib import Path

from testing_common import *
from testing_common import mock_task_ids

from docker.models.containers import ContainerCollection
from docker.models.images import ImageCollection

from nomad.api.job import Job
from nomad.api.jobs import Jobs
import socket

from typing import Callable
import pytest

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
            "device_serial_number": None,
            "sender_address": "0.0.0.0"
        }

def create_and_route(fs, mocked, task_id, config, uid="TESTFAKEUID") -> Tuple[List[str], str]:
    print("Mocked task_id is", task_id)

    new_task_id = "new-task-" + str(uuid.uuid1())

    mock_incoming_uid(config, fs, uid)

    mock_task_ids(mocked, task_id, new_task_id)
    # mocked.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    router.run_router()

    router.route_series.assert_called_once_with(task_id, uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, unittest.mock.ANY)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"catchall": True}, [f"{uid}#bar"], uid, unittest.mock.ANY, {})  # type: ignore

    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
        k.name for k in Path("/var/processing").glob("**/*") if k.is_file()
    ]

    mocked.patch("processor.process_series", new=mocked.spy(processor, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"], new_task_id

def create_and_route_priority(fs, mocked, task_id, config, uid="TESTFAKEUID") -> Tuple[List[str], List[str]]:
    print("Mocked task_id is", task_id)

    new_task_ids = ["new-task-" + str(uuid.uuid1()) for _ in range(1000)] # todo: support arbitrary number of tasks created?
    mock_incoming_uid(config, fs, uid)

    mock_task_ids(mocked, task_id, new_task_ids)
    router.run_router()

    router.route_series.assert_called_once_with(task_id, uid)  # type: ignore

    for case in Path("/var/processing").iterdir():
        if not case.is_dir(): continue
        assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
            k.name for k in case.iterdir() if k.is_file()
        ]

    created_tasks = [k.name for k in Path("/var/processing").iterdir() if k.is_dir()]
    assert set(created_tasks).issubset(set(new_task_ids))
    mocked.patch("processor.process_series", new=mocked.spy(processor, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"], created_tasks


@pytest.mark.asyncio
async def test_process_series_nomad(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    config = mercure_config(
        {"process_runner": "nomad", **config_partial},
    )
    fs.create_file(f"nomad/mercure-processor-template.nomad", contents="foo")
    mocked.patch.object(Jobs, "parse", new=lambda x, y: {})

    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id, config)

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
            "output": None,
        },
        "study": {},
        "nomad_info": fake_run.return_value,
    }

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}", "Moved files"),
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job dispatched"),
            call(task_event.PROCESS_COMPLETE, new_task_id, 1, "", "Processing complete"),
            call(task_event.COMPLETE, new_task_id, 0, "", "Task complete"),
        ]
    )
    common.monitor.send_task_event.reset_mock()  # type: ignore

    mock_incoming_uid(config,fs, "FAILEDFAILED")

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
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}", "Moved files"),
            call(task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job dispatched"),
            call(task_event.ERROR, new_task_id, 0, "", "Processing failed"),
        ]
    )



@pytest.mark.asyncio
async def test_process_series(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    global processor_path
    config = mercure_config(
        {"process_runner": "docker", **config_partial},
    )
    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id, config)
    processor_path = Path(f"/var/processing/{task_id}")

    # def fake_processor(tag, environment, volumes: Dict, **kwargs):
    #     global processor_path
    #     in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
    #     out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

    #     processor_path = in_.parent
    #     for child in in_.iterdir():
    #         print(f"Moving {child} to {out_ / child.name})")
    #         shutil.copy(child, out_ / child.name)

    #     return mocked.DEFAULT

    fake_run = mocked.Mock(return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs,mocked,False))  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    await processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    # process.process_series.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    uid_string = f"{os.getuid()}:{os.getegid()}"
    print("FAKE RUN CALLS",fake_run.call_args_list)
    fake_run.assert_has_calls(
        [
            call('busybox:stable', command='cat /etc/monai/app.json', entrypoint=''),
            call(
        config.modules["test_module"].docker_tag,
        environment={'HOLOSCAN_INPUT_PATH': '/tmp/data', 'HOLOSCAN_OUTPUT_PATH': '/tmp/output', "MERCURE_IN_DIR": "/tmp/data", "MERCURE_OUT_DIR": "/tmp/output",  'MONAI_INPUTPATH': '/tmp/data', 'MONAI_OUTPUTPATH': '/tmp/output'},
        user=uid_string,
        group_add=[os.getegid()],
        volumes=unittest.mock.ANY,
        runtime="runc",
        detach=True),
        call('busybox:stable-musl', volumes=unittest.mock.ANY, userns_mode='host', command=f'chown -R {uid_string} /tmp/output', detach=True)
        ]
    )
    print("FAKE RUN RESULT FILES", list((Path("/var/success")).glob("**/*")))
    assert [] == [k.name for k in Path("/var/processing").glob("**/*")]
    assert files + ["result.json"] == [k.name for k in (Path("/var/success")).glob("**/*") if k.is_file()]

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}", "Moved files"),
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
    files, new_task_id = create_and_route(fs, mocked, task_id, config)
    processor_path = Path(f"/var/processing/{new_task_id}")

    # def fake_processor(tag, environment, volumes: Dict, **kwargs):
    #     global processor_path
    #     in_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/data")))
    #     out_ = Path(next((k for k in volumes.keys() if volumes[k]["bind"] == "/tmp/output")))

    #     processor_path = in_.parent
    #     for child in in_.iterdir():
    #         print(f"Moving {child} to {out_ / child.name})")
    #         shutil.copy(child, out_ / child.name)
    #     with (in_ / "task.json").open("r") as fp:
    #         results = json.load(fp)["process"]["settings"]["result"]
    #     fs.create_file(out_ / "result.json", contents=json.dumps(results))
    #     return mocked.DEFAULT

    fake_run = mocked.Mock(return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs,mocked,False))  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    await processor.run_processor()

    # processor_path = next(Path("/var/processing").iterdir())
    # process.process_series.process_series.assert_called_once_with(str(processor_path))  # type: ignore

    uid_string = f"{os.getuid()}:{os.getegid()}"
    for m in partial["rules"]["catchall"]["processing_module"]:
        fake_run.assert_any_call(
                config.modules[m].docker_tag,
                environment={'HOLOSCAN_INPUT_PATH': '/tmp/data', 'HOLOSCAN_OUTPUT_PATH': '/tmp/output', "MERCURE_IN_DIR": "/tmp/data", "MERCURE_OUT_DIR": "/tmp/output",  'MONAI_INPUTPATH': '/tmp/data', 'MONAI_OUTPUTPATH': '/tmp/output'},
                user=uid_string,
                group_add=[os.getegid()],
                runtime="runc",
                volumes={
                    str(processor_path / "in"): {"bind": "/tmp/data", "mode": "rw"},
                    str(processor_path / "out"): {"bind": "/tmp/output", "mode": "rw"},
                },
                detach=True,
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
            "output": partial["modules"][m]["settings"]["result"],
        } for i, m in enumerate(partial["modules"])],
        "study": {},
        "nomad_info": None,
    }
    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "catchall", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "catchall"),
            call(task_event.MOVE, task_id, 1, f"/var/processing/{new_task_id}", "Moved files"),
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



@pytest.mark.asyncio
@pytest.mark.parametrize("is_offpeak", ((True,),(False,)))
async def test_priority_process(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture, is_offpeak: bool):
    global processor_path
    partial: Dict[str, Dict] = {
        "modules": {
            "test_module_1": Module(docker_tag="busybox:stable",settings={"fizz":"buzz","result":{"value":[1,2,3,4]}}).dict(),
            "test_module_2": Module(docker_tag="busybox:stable",settings={"fizz":"bing","result":{"value":[100,200,300,400]}}).dict(),
            "test_module_3": Module(docker_tag="busybox:stable",settings={"fizz":"bong","result":{"value":[1000,2000,3000,4000]}}).dict(),
        },
        "rules": {
            "normal_rule": Rule(
                rule="True",
                action="process",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="test_module_1",
                processing_retain_images=True,
                priority="normal"
            ).dict(),
            "urgent_rule": Rule(
                rule="True",
                action="process",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="test_module_2",
                processing_retain_images=True,
                priority="urgent"
            ).dict(),
            "offpeak_rule": Rule(
                rule="True",
                action="process",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="test_module_3",
                processing_retain_images=True,
                priority="offpeak"
            ).dict()
        },
    }
    config = mercure_config(
        {"process_runner": "docker", **partial},
    )
    task_id = str(uuid.uuid1())
    files, new_task_ids = create_and_route_priority(fs, mocked, task_id, config)
    processor_path = Path(f"/var/processing/")

    fake_run = mocked.Mock(return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs,mocked,False))  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)

    fake_pull = mocked.Mock(return_value=FakeImageContainer())  # type: ignore
    mocked.patch.object(ImageCollection, "pull", new=fake_pull)

    mocked.patch("common.helper._is_offpeak", lambda x,y,z: is_offpeak)

    # Can be added as a helper function
    def get_priority(task_folder: Path) -> str:
        taskfile_path = task_folder / mercure_names.TASKFILE
        with open(taskfile_path, "r") as f:
            task_instance = Task(**json.load(f))
        applied_rule = partial["rules"].get(task_instance.info.get("applied_rule"), {})
        priority = applied_rule.get('priority')
        return priority or ''

    tasks_folders = [processor_path / k for k in new_task_ids]
    for permutation in permutations(tasks_folders, len(tasks_folders)):
        prioritized_task = processor.prioritize_tasks(list(permutation),0) # check for default run
        assert prioritized_task and get_priority(prioritized_task) == "urgent"
        prioritized_task = processor.prioritize_tasks(list(permutation),2) # check for reverse run
        assert prioritized_task and get_priority(prioritized_task) in ["normal", "offpeak"] if is_offpeak else ["normal"]

    await processor.run_processor()
    assert len(processor.process_series.call_args_list) == 3 if is_offpeak else 2
    args, _ = processor.process_series.call_args_list[0]
    task_id = os.path.basename(args[0])
    task_folder = Path(f"/var/success/") / task_id
    assert get_priority(task_folder) == "urgent"