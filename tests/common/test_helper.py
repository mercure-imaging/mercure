from common.helper import is_ready_for_sending

pytest_plugins = ("pyfakefs",)

import os


def test_is_not_read_for_sending_for_empty_dir(fs):
    # "fs" is the reference to the fake file system
    fs.create_dir("/var/data/")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_locked(fs):
    # "fs" is the reference to the fake file system
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/.lock")
    assert not is_ready_for_sending("/var/data")


def test_is_not_read_for_sending_while_sending(fs):
    # "fs" is the reference to the fake file system
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/.sending")
    assert not is_ready_for_sending("/var/data")


def test_is_read_for_sending(fs):
    # "fs" is the reference to the fake file system
    fs.create_dir("/var/data/")
    fs.create_file("/var/data/a.dcm")
    assert is_ready_for_sending("/var/data")