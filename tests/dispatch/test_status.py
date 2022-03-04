import json
from common.types import Task

from dispatch.status import is_ready_for_sending, is_target_json_valid
from common.constants import mercure_names

pytest_plugins = ("pyfakefs",)
dummy_info = {
    "action": "route",
    "uid": "",
    "uid_type": "series",
    "triggered_rules": "",
    "mrn": "",
    "acc": "",
    "mercure_version": "",
    "mercure_appliance": "",
    "mercure_server": "",
}

# "fs" is the reference to the fake file system
def test_is_not_read_for_sending_for_empty_dir(fs):
    fs.create_dir("/var/data/")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_locked(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/" + mercure_names.LOCK)
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/" + mercure_names.PROCESSING)
    assert not is_ready_for_sending("/var/data")


def test_is_read_for_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/a.dcm")
    target = {"info": dummy_info, "dispatch": {"target_name": "test_target"}}
    fs.create_file("/var/data/task.json", contents=json.dumps(target))
    assert is_ready_for_sending("/var/data")


def test_read_target(fs):
    target = {"info": dummy_info, "dispatch": {"target_name": "test_target"}}
    fs.create_file("/var/data/" + mercure_names.TASKFILE, contents=json.dumps(target))
    task_content = is_target_json_valid("/var/data/")
    assert task_content
    read_dispatch = task_content.dispatch
    assert read_dispatch
    assert "target_name" in read_dispatch.dict()
