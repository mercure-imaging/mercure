import json
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from dispatch.send import execute

pytest_plugins = ("pyfakefs",)

@pytest.mark.skip(reason="focus on error case below")
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
    execute(Path(source), Path(success), error, 1, 1)

    assert not Path(source).exists()
    assert (Path(success) / "a").exists()
    assert (Path(success) / "a" / "target.json").exists()
    assert (Path(success) / "a" / "one.dcm").exists()



def test_execute_error_case(fs, mocker):
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_dir(error)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {"target_ip": "0.0.0.0", "target_aet_target": "a", "target_port": 90}
    fs.create_file("/var/data/source/a/target.json", contents=json.dumps(target))

    mocker.patch("dispatch.send.run", side_effect=CalledProcessError("Mock", cmd="None"))
    execute(Path(source), Path(success), Path(error), 1, 1)

    with open("/var/data/source/a/target.json", "r") as f:
        modified_target = json.load(f)

    assert not Path(source).exists()
    assert not (Path(success) / "a").exists()
    assert not (Path(success) / "a" / "target.json").exists()
    assert not (Path(success) / "a" / "one.dcm").exists()
    assert modified_target["retries"] == 1
