"""
test_router.py
==============
"""
import os
import router
import json
from pprint import pprint
from common.types import *
import routing
import routing.generate_taskfile
from pathlib import Path

from testing_common import load_config


def test_route_series(fs, mocker):
    load_config(
        fs,
        {
            "rules": {
                "catchall": {
                    "rule": "True",
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
        },
    )

    mocker.patch("routing.route_series.push_series_serieslevel", new=mocker.spy(routing.route_series, "push_series_serieslevel"))
    mocker.patch(
        "routing.route_series.push_serieslevel_outgoing",
        new=mocker.spy(routing.route_series, "push_serieslevel_outgoing"),
    )
    mocker.patch("routing.generate_taskfile.create_series_task", new=mocker.spy(routing.generate_taskfile, "create_series_task"))

    mocker.patch("router.route_series", new=mocker.spy(router, "route_series"))
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})

    uid = "UIDUIDUID"
    fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

    router.run_router()

    router.route_series.assert_called_once_with(uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with({"catchall": True}, [f"{uid}#bar"], uid, {})  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with({"catchall": True}, [f"{uid}#bar"], uid, {}, {"test_target": "catchall"})  # type: ignore

    out_path = next(Path("/var/outgoing").iterdir())
    assert ["task.json", f"{uid}#bar.dcm", f"{uid}#bar.tags"] == [k.name for k in Path("/var/outgoing").glob("**/*") if k.is_file()]
    with open(out_path / "task.json") as e:
        task: Task = json.load(e)
        assert task["dispatch"]["target_name"] == "test_target"  # type: ignore
        assert task["info"]["uid"] == uid
        assert task["info"]["uid_type"] == "series"
        assert task["info"]["triggered_rules"]["catchall"] == True  # type: ignore
        assert task["process"] == {}
        assert task["study"] == {}

    # routing.generate_taskfile.create_series_task.assert_called_once()


def test_router_no_syntax_errors():
    """Checks if router.py can be started."""
    assert router
