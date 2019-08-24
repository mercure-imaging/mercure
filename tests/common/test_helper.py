from common.helper import is_ready_for_sending, has_been_send

pytest_plugins = ("pyfakefs",)

import os

# "fs" is the reference to the fake file system
def test_is_not_read_for_sending_for_empty_dir(fs):
    fs.create_dir("/var/data/")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_locked(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/.lock")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/.sending")
    assert not is_ready_for_sending("/var/data")


def test_is_read_for_sending(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/a.dcm")
    fs.create_file("/var/data/target.json")
    assert is_ready_for_sending("/var/data")


def test_has_been_send(fs):
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/sent.txt")
    assert has_been_send("/var/data/")


def test_has_been_send_not(fs):
    fs.create_dir("/var/data/")
    assert not has_been_send("/var/data/")
