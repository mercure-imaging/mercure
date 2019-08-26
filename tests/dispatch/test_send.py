import json
import os
from pathlib import Path
import unittest.mock as mock
from pyfakefs.fake_filesystem_unittest import Patcher

from dispatch.send import execute

pytest_plugins = ("pyfakefs",)


def test_execute_successful_case(fs, mocker):
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {"target_ip": "0.0.0.0", "target_aet_target": "a", "target_port": 90}
    fs.create_file("/var/data/source/a/target.json", contents=json.dumps(target))

    mocker.patch("dispatch.send.run", return_value=0)
    execute(Path(source), Path(success), error)

    assert not Path(source).exists()
    assert (Path(success) / "a").exists()
    assert (Path(success) / "a" / "target.json").exists()
    assert (Path(success) / "a" / "one.dcm").exists()

