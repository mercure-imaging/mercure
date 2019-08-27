import json
import os
import time
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from dispatch.retry import increase_retry


def test_execute_increase(fs, mocker):
    source = "/var/data"
    fs.create_dir(source)
    target = {"target_ip": "0.0.0.0", "target_aet_target": "a", "target_port": 90}
    fs.create_file("/var/data/target.json", contents=json.dumps(target))
    result = increase_retry(source, 5, 50)

    with open("/var/data/target.json", "r") as f:
        modified_target = json.load(f)

    assert modified_target["retries"] == 1
    assert modified_target["next_retry_at"]
    assert result


def test_execute_increase_fail(fs, mocker):
    source = "/var/data"
    fs.create_dir(source)
    target = {
        "target_ip": "0.0.0.0",
        "target_aet_target": "a",
        "target_port": 90,
        "retries": 5,
    }
    fs.create_file("/var/data/target.json", contents=json.dumps(target))
    result = increase_retry(source, 5, 50)

    assert not result

