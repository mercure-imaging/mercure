import json
import os
import time
from pathlib import Path
from subprocess import CalledProcessError

import pytest
import uuid

from webinterface.queue import restart_dispatch
from common.constants import mercure_names, mercure_actions

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
    "dispatch": {
        "target_name": ["fakeTarget"],
        "status": {
            "fakeTarget": {
                "state": "waiting",
                "time": "2024-10-03 16:03:35"
            }
        },
    }
}


# write a test case for restart_job function
def test_restart_dispatch_success(fs):
    error_folder = Path("/var/error")
    outgoing_folder = Path("/var/outgoing")
    fs.create_dir(error_folder)
    fs.create_dir(outgoing_folder)

    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert "success" in response

def test_restart_dispatch_fail(fs):
    error_folder = Path("/var/error")
    outgoing_folder = Path("/var/outgoing")
    fs.create_dir(error_folder)
    fs.create_dir(outgoing_folder)

    # missing task file
    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    response = restart_dispatch(task_folder, outgoing_folder)
    assert "error" in response
    assert response["error_code"] == 2

    # presence of lock, processing, or error file
    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.LOCK)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert "error" in response
    assert response["error_code"] == 1

    # mercure action not suitable for dispatching
    dummy_info = {
        "action": mercure_actions.DISCARD,
        "uid": "",
        "uid_type": "series",
        "sender_address": "localhost",
    }
    dummy_task_file["info"] = dummy_info
    task_id = str(uuid.uuid1())
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert "error" in response
    assert response["error_code"] == 3

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
    task_folder = Path(error_folder) / task_id
    fs.create_dir(task_folder)
    fs.create_file(task_folder / mercure_names.TASKFILE, contents=json.dumps(dummy_task_file))
    response = restart_dispatch(task_folder, outgoing_folder)
    assert "error" in response
    assert response["error_code"] == 4