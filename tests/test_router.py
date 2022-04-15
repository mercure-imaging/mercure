"""
test_router.py
==============
"""
import importlib
import os
import stat
from typing import Tuple
from unittest.mock import call
import json
from pprint import pprint
import uuid

import pytest
from common.helper import FileLock
from common.monitor import m_events, task_event, severity
from common.types import *
import common
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs import fake_filesystem
import routing
import routing.generate_taskfile
import router, dispatcher
from pathlib import Path

from testing_common import *

# import common.config as config

rules = {
    "rules": {
        "route_study": Rule(
            rule="""@StudyDescription@ == "foo" """, action="route", target="test_target_2", action_trigger="study"
        ).dict(),
        "route_series": Rule(
            rule="""@SeriesInstanceUID@ == "foo" """,
            target="test_target",
            action="route",
            action_trigger="series",
        ).dict(),
        "broken": Rule(rule=" 1/0 ", target="test_target", action="route", action_trigger="series").dict(),
    }
}


def create_series(mocked, fs, config, tags) -> Tuple[str, str]:
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    mocked.patch("uuid.uuid1", new=lambda: task_id)

    fs.create_file(f"{config.incoming_folder}/{series_uid}#baz.dcm", contents="asdfasdfafd")
    fs.create_file(f"{config.incoming_folder}/{series_uid}#baz.tags", contents=tags)
    return task_id, series_uid


def test_route_series_fail1(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesInstanceUID": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, "foobar")

    common.monitor.configure("router", "test", config.bookkeeper)
    router.run_router()
    print(common.monitor.send_task_event.call_args_list)  # type: ignore
    common.monitor.send_task_event.assert_any_call(  # type: ignore
        task_event.ERROR,
        task_id,
        0,
        "",
        f"Invalid tag for series {series_uid}",
    )


def test_route_series_fail2(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesInstanceUID": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, json.dumps(tags))

    router.run_router()
    common.monitor.send_event.assert_any_call(  # type: ignore
        m_events.CONFIG_UPDATE,
        severity.ERROR,
        "Invalid rule encountered:  1/0 ",
    )
    common.monitor.send_task_event.reset_mock()  # type: ignore


def test_route_series_fail3(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesInstanceUID": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, json.dumps(tags))

    real_mkdir = os.mkdir

    def no_create_destination(dest):
        if config.outgoing_folder in dest:
            raise Exception("no")
        else:
            real_mkdir(dest)

    mocked.patch("os.mkdir", new=no_create_destination)
    router.run_router()
    common.monitor.send_task_event.assert_any_call(  # type: ignore
        task_event.ERROR,
        task_id,
        0,
        "",
        f"Unable to create outgoing folder {config.outgoing_folder}/{task_id}",
    )

    def fake_create_destination(dest):
        if config.outgoing_folder in dest:
            pass
        else:
            real_mkdir(dest)

    mocked.patch("os.mkdir", new=fake_create_destination)
    router.run_router()
    common.monitor.send_task_event.assert_any_call(  # type: ignore
        task_event.ERROR,
        task_id,
        0,
        "",
        f"Creating folder not possible {config.outgoing_folder}/{task_id}",
    )


def test_route_series_fail4(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesInstanceUID": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, json.dumps(tags))

    mocked.patch("shutil.move", side_effect=Exception("no moving"))
    router.run_router()
    common.monitor.send_task_event.assert_any_call(  # type: ignore
        task_event.ERROR,
        task_id,
        0,
        "",
        f"Problem while pushing file to outgoing {series_uid}#baz\nSource folder {config.incoming_folder}/\nTarget folder {config.outgoing_folder}/{task_id}/",
    )


def task_will_dispatch_to(task, config, fake_process) -> None:
    t = config.targets[task.dispatch.target_name]
    expect_command = f"dcmsend {t.ip} {t.port} +sd /var/outgoing/{task.id} -aet {t.aet_source} -aec {t.aet_target} -nuc +sp '*.dcm' -to 60 +crf /var/outgoing/{task.id}/sent.txt"  # type: ignore
    fake_process.register(expect_command)  # type: ignore
    common.monitor.configure("dispatcher", "test", config.bookkeeper)
    dispatcher.dispatch("")

    assert Path(f"/var/success/{task.id}").is_dir()

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.DISPATCH, task.id, 1, task.dispatch.target_name, ""),
            call(task_event.MOVE, task.id, 0, "/var/success", ""),
        ],
    )


def test_route_study(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)

    study_uid = str(uuid.uuid4())
    rule_name = "route_study"
    tags = {
        "StudyInstanceUID": study_uid,
        "SeriesInstanceUID": "bar",
        "StudyDescription": "foo",
        "SeriesDescription": "series_desc",
    }
    task_id, series_uid = create_series(mocked, fs, config, json.dumps(tags))
    common.monitor.configure("router", "test", config.bookkeeper)

    router.run_router()
    router.route_studies.assert_called_once()  # type: ignore
    routing.route_studies.route_study.assert_called_once()  # type: ignore
    routing.route_studies.move_study_folder.assert_called_with(task_id, f"{study_uid}#{rule_name}", "OUTGOING")  # type: ignore

    out_path = Path(f"/var/outgoing/{task_id}")

    try:
        assert ["task.json", f"{series_uid}#baz.dcm", f"{series_uid}#baz.tags"] == [
            k.name for k in out_path.glob("*") if k.is_file()
        ]
    except AssertionError as k:
        message = f"Expected results are missing: {k.args[0]}"
        k.args = (message,)  # wrap it up in new tuple
        raise

    with open(out_path / "task.json") as e:
        task: Task = Task(**json.load(e))

    assert task.id == task_id
    assert task.dispatch.target_name == "test_target_2"  # type: ignore
    assert task.info.uid == study_uid
    assert task.info.uid_type == "study"
    assert task.info.triggered_rules["route_study"] == True  # type: ignore
    assert task.process == {}
    assert isinstance(task.study, TaskStudy)
    assert task.study.study_uid == study_uid
    assert task.study.complete_trigger == "timeout"
    assert task.study.received_series == [tags["SeriesDescription"]]

    common.monitor.send_register_task.assert_called_once_with(task)  # type: ignore

    task_will_dispatch_to(task, config, fake_process)
    # common.monitor.send_task_event.assert_any_call(  # type: ignore
    #     "ROUTED",
    #     task_id,
    #     0,
    #     "",
    #     f"Routed to test_target",
    # )


def test_route_series(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)
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
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"route_series": True}, [f"{series_uid}#bar"], series_uid, tags)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"route_series": True}, [f"{series_uid}#bar"], series_uid, tags, {"test_target": ["route_series"]})  # type: ignore

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTERED, task_id, 1, "", "Registered series."),
            call(task_event.ERROR, task_id, 0, "", 'Invalid rule encountered: @StudyDescription@ == "foo" '),
            call(task_event.ERROR, task_id, 0, "", "Invalid rule encountered:  1/0 "),
            call(task_event.ROUTE, task_id, 1, "test_target", "route_series"),
            call(task_event.MOVE, task_id, 1, f"/var/outgoing/{task_id}", ""),
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
    assert task.info.triggered_rules["route_series"] == True  # type: ignore
    assert task.process == {}
    assert task.study == {}
    common.monitor.send_register_task.assert_called_once_with(task)  # type: ignore

    task_will_dispatch_to(task, config, fake_process)
    # print(common.monitor.send_event.call_args_list)
    # common.monitor.send_event.assert_not_called()


def test_router_no_syntax_errors():
    """Checks if router.py can be started."""
    assert router
