import copy
import json
import time
import unittest
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import common.config as config
import pytest
import routing
import routing.generate_taskfile
from common.constants import mercure_actions, mercure_names
from common.types import Config, Module, Rule
from dispatch.send import execute
from docker.models.containers import ContainerCollection
from process import processor
from pytest_mock import MockerFixture
from routing import router
from tests.testing_common import FakeDockerContainer, make_fake_processor, mock_incoming_uid, mock_task_ids
from webinterface.queue import RestartTaskErrors, restart_dispatch

logger = config.get_logger()

processor_path = Path()
config_partial: Dict[str, Dict] = {
    "modules": {
        "test_module": Module(docker_tag="busybox:stable", settings={"fizz": "buzz"}).dict(),
    },
    "rules": {
        "catchall": Rule(
            rule="True",
            action="both",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    },
}

dispatch_info = {
    "target_name": ["test_target"],
    "retries": 5,
    "next_retry_at": time.time() - 5,
    "status": {
        "test_target": {
            "state": "waiting",
            "time": "2024-10-03 16:03:35"
        }
    }
}

dummy_task_file = {
    "info": {
        "action": "both",
        "uid": "",
        "uid_type": "series",
        "mrn": "",
        "acc": "",
        "sender_address": "localhost",
        "mercure_version": "",
        "mercure_appliance": "",
        "mercure_server": "",
        "device_serial_number": ""
    },
    "id": "",
    "dispatch": dispatch_info,
}

dummy_info = {
    "action": "both",
    "uid": "",
    "uid_type": "series",
    "triggered_rules": "",
    "mrn": "",
    "acc": "",
    "sender_address": "localhost",
    "mercure_version": "",
    "mercure_appliance": "",
    "mercure_server": "",
}


def test_restart_dispatch_success(fs, mocked):
    error_folder = Path("/var/data/error")
    outgoing_folder = Path("/var/data/outgoing")
    success_folder = Path("/var/data/success")
    fs.create_dir(error_folder)
    fs.create_dir(outgoing_folder)
    fs.create_dir(success_folder)

    task_id = str(uuid.uuid1())
    target = {
        "id": task_id,
        "info": dummy_info,
        "dispatch": copy.deepcopy(dispatch_info)
    }

    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / "one.dcm")
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(target))
    response = restart_dispatch(task_folder, outgoing_folder)

    assert "success" in response
    assert not task_folder.exists()
    assert (outgoing_folder / task_id).exists()
    assert (outgoing_folder / task_id / "one.dcm").exists()
    assert (outgoing_folder / task_id).exists()
    task_file_json = json.loads((outgoing_folder / task_id / mercure_names.TASKFILE).read_text())
    assert task_file_json["dispatch"]["retries"] is None

    # Once moved to outgoing folder, verify the execution/dispatching
    def fake_check_output(command, encoding="utf-8", stderr=None, **opts):
        result_file = Path(command[-1])
        fs.create_file(result_file, contents="dummy report file for testing")
        return "Success"
    mocked.patch("dispatch.target_types.base.check_output", side_effect=fake_check_output)
    dummy_parse_dcmsend_result = {
        "summary": {
            "sop_instances": 1,
            "successful": 1,
        }
    }
    mocked.patch("dispatch.target_types.builtin.parse_dcmsend_result", return_value=dummy_parse_dcmsend_result)
    response = execute(outgoing_folder / task_id, success_folder, error_folder, 1, 1)

    assert not (outgoing_folder / task_id).exists()
    assert (success_folder / task_id).exists()
    assert (success_folder / task_id / mercure_names.TASKFILE).exists()
    assert (success_folder / task_id / "one.dcm").exists()


def test_restart_dispatch_fail(fs):
    error_folder = Path("/var/data/error")
    outgoing_folder = Path("/var/data/outgoing")

    # missing task file
    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    response = restart_dispatch(task_folder, outgoing_folder)
    assert not (outgoing_folder / task_id).exists()
    assert "error" in response
    assert response["error_code"] == RestartTaskErrors.NO_TASK_FILE

    # presence of lock, processing, or error file
    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.LOCK)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert not (outgoing_folder / task_id).exists()
    assert "error" in response
    assert response["error_code"] == RestartTaskErrors.TASK_NOT_READY

    # mercure action not suitable for dispatching
    dummy_info = {
        "action": mercure_actions.DISCARD,
        "uid": "",
        "uid_type": "series",
        "sender_address": "localhost",
    }
    dummy_task_file["info"] = dummy_info
    task_id = str(uuid.uuid1())
    task_folder = error_folder / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert not (outgoing_folder / task_id).exists()
    assert "error" in response
    assert response["error_code"] == RestartTaskErrors.WRONG_JOB_TYPE

    # missing dispatch information
    dummy_info = {
        "action": mercure_actions.BOTH,
        "uid": "",
        "uid_type": "series",
        "sender_address": "localhost",
    }
    dummy_task_file["info"] = dummy_info
    dummy_task_file["dispatch"] = {}
    task_id = str(uuid.uuid1())
    task_folder = error_folder / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert not (outgoing_folder / task_id).exists()
    assert "error" in response
    assert response["error_code"] == RestartTaskErrors.NO_DISPATCH_STATUS


# Taken directly from tests/test_processor.py
def create_and_route(fs, mocked, task_id, config, uid="TESTFAKEUID") -> Tuple[List[str], str]:
    print("Mocked task_id is", task_id)

    new_task_id = "new-task-" + str(uuid.uuid1())

    mock_incoming_uid(config, fs, uid)

    mock_task_ids(mocked, task_id, new_task_id)
    # mocked.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    router.run_router()

    router.route_series.assert_called_once_with(task_id, uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(  # type: ignore
        task_id, {"catchall": True}, [f"{uid}#bar"], uid, unittest.mock.ANY)
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(  # type: ignore
        task_id, {"catchall": True}, [f"{uid}#bar"], uid, unittest.mock.ANY, {})

    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [
        k.name for k in Path("/var/processing").glob("**/*") if k.is_file()
    ]

    # mocked.patch("process.processor.process_series", new=mocked.spy(processor, "process_series"))
    return ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"], new_task_id


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_processor", (True, False))
async def test_dispatching_with_processing(fs, mercure_config: Callable[[Dict], Config],
                                           mocked: MockerFixture, fail_processor: bool):
    global processor_path
    config = mercure_config(
        {"process_runner": "docker", **config_partial},
    )
    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id, config)
    processor_path = Path(f"/var/processing/{task_id}")

    fake_run = mocked.Mock(return_value=FakeDockerContainer(),
                           side_effect=make_fake_processor(fs, mocked, fail_processor))  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    await processor.run_processor()
    assert not processor_path.exists()

    folder_path = None
    outgoing_folder = Path("/var/outgoing")
    success_folder = Path("/var/success")
    error_folder = Path("/var/error")
    if fail_processor:  # The processing failed, so retrying dispatching should not work
        folder_path = Path("/var/error") / new_task_id
        response = restart_dispatch(folder_path, outgoing_folder)
        assert "error" in response
        assert not (outgoing_folder / new_task_id).exists()
        return

    # Verify that restarting the dispatching worked
    folder_path = success_folder / new_task_id
    loaded_task = json.loads((folder_path / mercure_names.TASKFILE).read_text())
    loaded_task["dispatch"] = copy.deepcopy(dispatch_info)
    with open(folder_path / mercure_names.TASKFILE, "w") as json_file:
        json.dump(loaded_task, json_file)
    response = restart_dispatch(folder_path, outgoing_folder)
    assert "success" in response
    assert not folder_path.exists()  # it's not in the success folder
    assert (outgoing_folder / new_task_id).exists()  # it's in the outgoing folder ready to retry
    task_file_json = json.loads((outgoing_folder / new_task_id / mercure_names.TASKFILE).read_text())
    assert task_file_json["dispatch"]["retries"] is None  # indicates that it hasn't retried at all

    # Once moved to outgoing folder, verify the execution/dispatching
    def fake_check_output(command, encoding="utf-8", stderr=None, **opts):
        result_file = Path(command[-1])
        fs.create_file(result_file, contents="dummy report file for testing")
        return "Success"
    mocked.patch("dispatch.target_types.base.check_output", side_effect=fake_check_output)
    dummy_parse_dcmsend_result = {
        "summary": {
            "sop_instances": 1,
            "successful": 1,
        }
    }
    mocked.patch("dispatch.target_types.builtin.parse_dcmsend_result", return_value=dummy_parse_dcmsend_result)
    response = execute(outgoing_folder / new_task_id, success_folder, error_folder, 1, 1)
    assert not (outgoing_folder / new_task_id).exists()  # it's not outgoing anymore
    assert (success_folder / new_task_id).exists()  # dispatching succeeded
    assert (success_folder / new_task_id / mercure_names.TASKFILE).exists()
    assert (success_folder / new_task_id / "result.json").exists()
