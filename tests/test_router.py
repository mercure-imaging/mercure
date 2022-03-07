"""
test_router.py
==============
"""
import importlib
import stat
from unittest.mock import call
import json
from pprint import pprint
import uuid

import pytest
from common.types import *
import common
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs import fake_filesystem
import routing
import routing.generate_taskfile
import router, dispatcher
from pathlib import Path

from testing_common import load_config, mocked

# import common.config as config

rules = {
    "rules": {
        "catchall": {
            "rule": """@SeriesInstanceUID@ == "foo" """,
            "target": "test_target",
            "disabled": "False",
            "fallback": "False",
            "contact": "",
            "comment": "",
            "tags": "",
            "action": "route",
            "action_trigger": "series",
            "study_trigger_condition": "timeout",
            "study_trigger_series": "",
            "priority": "normal",
            "processing_module": "",
            "processing_settings": "",
            "notification_webhook": "",
            "notification_payload": "",
            "notification_trigger_reception": "False",
            "notification_trigger_completion": "False",
            "notification_trigger_error": "False",
        }
    }
}


def test_route_series_fail(fs: FakeFilesystem, mocked, fake_process):
    config = load_config(fs, rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())
    mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = {"SeriesInstanceUID": "foo"}
    fs.create_file(f"/var/incoming/{series_uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{series_uid}#bar.tags", contents="error")
    # fake_filesystem.set_uid(1)
    common.monitor.configure("router", "test", config.bookkeeper)
    # with pytest.raises(PermissionError):
    # routing.route_series(series_uid, config)
    router.run_router()
    common.monitor.send_task_event.assert_called_with(
        "ERROR",
        task_id,
        0,
        "",
        f"Invalid tag for series {series_uid}",
    )
    # fs.remove(f"/var/incoming/{series_uid}#bar.tags")
    # fs.create_file(f"/var/incoming/{series_uid}#bar.tags", contents="error", st_mode=stat.S_IFDIR | 0o333)
    # router.run_router()


def test_route_series(fs: FakeFilesystem, mocked, fake_process):
    config = load_config(fs, rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())
    mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = {"SeriesInstanceUID": "foo"}
    fs.create_file(f"/var/incoming/{series_uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{series_uid}#bar.tags", contents=json.dumps(tags))

    common.monitor.configure("router", "test", config.bookkeeper)
    router.run_router()

    common.monitor.send_register_series.assert_called_once_with({"SeriesInstanceUID": "foo"})  # type: ignore
    common.monitor.send_register_task.assert_called_once()  # type: ignore
    router.route_series.assert_called_once_with(task_id, series_uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"catchall": True}, [f"{series_uid}#bar"], series_uid, tags)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"catchall": True}, [f"{series_uid}#bar"], series_uid, tags, {"test_target": ["catchall"]})  # type: ignore

    common.monitor.send_task_event.assert_has_calls(
        [
            call("REGISTERED", task_id, 1, "", "Registered series"),
            call("ROUTE", task_id, 1, "test_target", "catchall"),
            call("MOVE", task_id, 1, f"/var/outgoing/{task_id}", ""),
        ]
    )
    out_path = next(Path("/var/outgoing").iterdir())
    try:
        assert ["task.json", f"{series_uid}#bar.dcm", f"{series_uid}#bar.tags"] == [
            k.name for k in Path("/var/outgoing").glob("**/*") if k.is_file()
        ]
    except AssertionError as k:
        message = f"Expected results are missing: {k.args[0]}"
        k.args = (message,)  # wrap it up in new tuple
        raise

    with open(out_path / "task.json") as e:
        task: Task = Task(**json.load(e))
    assert task.id == task_id
    assert task.dispatch.target_name == "test_target"  # type: ignore
    assert task.info.uid == series_uid
    assert task.info.uid_type == "series"
    assert task.info.triggered_rules["catchall"] == True  # type: ignore
    assert task.process == {}
    assert task.study == {}
    common.monitor.send_register_task.assert_called_once_with(task)

    fake_process.register(
        f"dcmsend {config.targets['test_target'].ip} {config.targets['test_target'].port} +sd /var/outgoing/{task_id} -aet -aec foo -nuc +sp *.dcm -to 60 +crf /var/outgoing/{task_id}/sent.txt"
    )
    common.monitor.configure("dispatcher", "test", config.bookkeeper)
    dispatcher.dispatch("")

    assert Path(f"/var/success/{task_id}").is_dir()

    common.monitor.send_task_event.assert_has_calls(
        [call("DISPATCH", task_id, 1, "test_target", ""), call("MOVE", task_id, 0, "/var/success", "")],
    )
    # print(common.monitor.send_event.call_args_list)
    # common.monitor.send_event.assert_not_called()


def test_router_no_syntax_errors():
    """Checks if router.py can be started."""
    assert router
