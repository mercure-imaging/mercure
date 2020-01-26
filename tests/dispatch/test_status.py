import json

from dispatch.status import (has_been_send, is_ready_for_sending,
                           is_target_json_valid)
from common.constants import mercure_names

pytest_plugins = ("pyfakefs",)


# "fs" is the reference to the fake file system
def test_is_not_read_for_sending_for_empty_dir(fs):
    fs.create_dir("/var/data/")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_locked(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/"+mercure_names.LOCK)
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/"+mercure_names.PROCESSING)
    assert not is_ready_for_sending("/var/data")

                   
def test_is_read_for_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/a.dcm")
    target = { "dispatch": {"target_ip": "0.0.0.0", "target_port": 104, "target_aet_target": "ANY" } }
    fs.create_file("/var/data/task.json", contents=json.dumps(target))
    assert is_ready_for_sending("/var/data")


def test_has_been_send(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/"+mercure_names.SENDLOG)
    assert has_been_send("/var/data/")


def test_has_been_send_not(fs):
    fs.create_dir("/var/data/")
    assert not has_been_send("/var/data/")


def test_read_target(fs):
    target = { "dispatch": { "target_ip": "0.0.0.0", "target_port": 104, "target_aet_target": "ANY" } } 
    fs.create_file("/var/data/"+mercure_names.TASKFILE, contents=json.dumps(target))
    read_target = is_target_json_valid("/var/data/")
    assert read_target
    assert "target_ip" in read_target
    assert "target_port" in read_target
    assert "target_aet_target" in read_target


def test_read_target_with_missing_key(fs):
    target = { "dispatch": {"target_port": 104, "target_aet_target": "ANY" } }
    fs.create_file("/var/data/"+mercure_names.TASKFILE, contents=json.dumps(target))
    read_target = is_target_json_valid("/var/data/")
    assert not read_target
