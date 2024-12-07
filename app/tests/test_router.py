"""
test_router.py
==============
"""
import json
import os
import unittest
import uuid
from pathlib import Path
from typing import Tuple
from unittest.mock import call

import common
import routing.generate_taskfile
from common.monitor import m_events, severity, task_event
from common.types import *
from dispatch import dispatcher
from pyfakefs.fake_filesystem import FakeFilesystem
from routing import router
from testing_common import *
from testing_common import mock_task_ids

# import common.config as config

rules = {
    "rules": {
        "route_study": Rule(
            rule="""@StudyDescription@ == "foo" """, action="route", target="test_target_2", action_trigger="study"
        ).dict(),
        "route_series": Rule(
            rule="""tags.SeriesDescription == "foo" """,
            target="test_target",
            action="route",
            action_trigger="series",
        ).dict(),
        "route_series_new_rule": Rule(
            rule="""tags.SeriesDescription == "new_rule" """,
            target="test_target",
            action="route",
            action_trigger="series",
        ).dict(),
        "route_series_bad_tag": Rule(
            rule=""""Garbage" in tags.BADTAG """,
            target="test_target",
            action="route",
            action_trigger="series",
        ).dict(),
        "broken": Rule(rule=" 1/0 ", target="test_target", action="route", action_trigger="series").dict(),
    }
}


def create_series(mocked, fs, config, tags, name="bar") -> Tuple[str, str]:
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    mocked.patch("uuid.uuid1", new=lambda: task_id)

    mock_incoming_uid(config, fs, series_uid, tags, name)
    return task_id, series_uid

def test_route_series_fail1(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"asdfasdfas": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, tags)

    tags_file = next(Path(config.incoming_folder).glob("**/*.tags"))
    with open(tags_file,'a') as f:
        f.write("garbage")
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

    tags = {"SeriesInstanceUID": "asdfasdfasdf"}
    task_id, series_uid = create_series(mocked, fs, config, tags)

    router.run_router()
    common.monitor.send_event.assert_any_call(  # type: ignore
        m_events.CONFIG_UPDATE,
        severity.ERROR,
        "Invalid rule encountered:  1/0 ",
    )
    common.monitor.send_task_event.assert_any_call(task_event.DISCARD, task_id, 1, "","Discard by default.")  # type: ignore
    common.monitor.send_task_event.reset_mock()  # type: ignore

def test_route_series_fail3(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesDescription": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, tags)

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

    # def fake_create_destination(dest):
    #     if dest == config.outgoing_folder:
    #         pass
    #     else:
    #         real_mkdir(dest)

    # mocked.patch("os.mkdir", new=fake_create_destination)
    # router.run_router()
    # common.monitor.send_task_event.assert_any_call(  # type: ignore
    #     task_event.ERROR,
    #     task_id,
    #     0,
    #     "",
    #     f"Creating folder not possible {config.outgoing_folder}/{task_id}",
    # )

def test_route_series_fail4(fs: FakeFilesystem, mercure_config, mocked):
    config = mercure_config(rules)

    tags = {"SeriesDescription": "foo"}
    task_id, series_uid = create_series(mocked, fs, config, tags, name="baz")

    mocked.patch("shutil.move", side_effect=Exception("no moving"))
    mocked.patch("shutil.copy", side_effect=Exception("no copying"))
    router.run_router()
    common.monitor.send_task_event.assert_any_call(  # type: ignore
        task_event.ERROR,
        task_id,
        0,
        "",
        f"Problem while pushing file to outgoing [{series_uid}#baz]\nSource folder {config.incoming_folder}/{series_uid}\nTarget folder {config.outgoing_folder}/{task_id}",
    )
    assert list(Path(config.outgoing_folder).glob("**/*.dcm")) == []

def task_will_dispatch_to(task, config, fake_process) -> None:
    for target_item in task.dispatch.target_name:
        t = config.targets[target_item]
        expect_command = f"dcmsend {t.ip} {t.port} +sd /var/outgoing/{task.id} -aet -aec {t.aet_target} -nuc +sp *.dcm -to 60 +crf /var/outgoing/{task.id}/sent.txt"  # type: ignore
        fake_process.register(expect_command)  # type: ignore
        common.monitor.configure("dispatcher", "test", config.bookkeeper)
        dispatcher.dispatch()

        assert Path(f"/var/success/{task.id}").is_dir()

        common.monitor.send_task_event.assert_has_calls(  # type: ignore
            [
                call(task_event.DISPATCH_BEGIN, task.id, 1, target_item, "Routing job running"),
                call(task_event.DISPATCH_COMPLETE, task.id, 1, target_item, "Routing job complete"),
            ],
        )
    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.MOVE, task.id, 0, f"/var/success/{task.id}", "Moved to success folder"),
        ],
    )


def test_route_study(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)

    study_uid = str(uuid.uuid4())
    rule_name = "route_study"
    tags = {
        "StudyInstanceUID": study_uid,
        "StudyDescription": "foo",
        "SeriesDescription": "series_desc",
    }
    task_id, series_uid = create_series(mocked, fs, config, tags, "baz")
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
    assert task.dispatch.target_name == ["test_target_2"]  # type: ignore
    assert task.info.uid == study_uid
    assert task.info.uid_type == "study"
    assert task.info.triggered_rules["route_study"] == True  # type: ignore
    assert task.process == {}
    assert isinstance(task.study, TaskStudy)
    assert task.study.study_uid == study_uid
    assert task.study.complete_trigger == "timeout"
    assert task.study.received_series == [tags["SeriesDescription"]]

    common.monitor.send_update_task.assert_called_with(task)  # type: ignore

    task_will_dispatch_to(task, config, fake_process)
    # common.monitor.send_task_event.assert_any_call(  # type: ignore
    #     "ROUTED",
    #     task_id,
    #     0,
    #     "",
    #     f"Routed to test_target",
    # )

def test_route_series_success(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    new_task_id = "new-task-" + str(uuid.uuid1())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = {"SeriesDescription": "foo"}
    mock_incoming_uid(config, fs, series_uid, tags)


    common.monitor.configure("router", "test", config.bookkeeper)
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    common.monitor.send_register_series.call_args_list[0][0][0]["SeriesDescription"] == "foo"  # type: ignore
    common.monitor.send_register_task.assert_any_call(task_id, series_uid)  # type: ignore
    router.route_series.assert_called_once_with(task_id, series_uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"route_series": True}, [f"{series_uid}#bar"], series_uid, unittest.mock.ANY)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"route_series": True}, [f"{series_uid}#bar"], series_uid, unittest.mock.ANY, {"test_target": ["route_series"]})  # type: ignore

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.ERROR, task_id, 0, "", "Invalid rule encountered:  1/0 "),
            call(task_event.REGISTER, task_id, 1, "route_series", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "route_series"),
            call(task_event.MOVE, task_id, 1, f"/var/outgoing/{new_task_id}", "Moved files"),
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
    assert task.id == new_task_id
    assert task.dispatch.target_name == ["test_target"]  # type: ignore
    assert task.info.uid == series_uid
    assert task.info.uid_type == "series"
    assert task.info.triggered_rules["route_series"] == True  # type: ignore
    assert task.process == {}
    assert task.study == {}
    common.monitor.send_register_task.assert_any_call(task_id, series_uid)  # type: ignore
    common.monitor.send_register_task.assert_any_call(new_task_id, series_uid, task_id)  # type: ignore

    task_will_dispatch_to(task, config, fake_process)
    # print(common.monitor.send_event.call_args_list)
    # common.monitor.send_event.assert_not_called()


def test_route_series_new_rule(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    new_task_id = "new-task-" + str(uuid.uuid1())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = {"SeriesDescription": "new_rule"}
    mock_incoming_uid(config, fs, series_uid, tags)

    common.monitor.configure("router", "test", config.bookkeeper)
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    common.monitor.send_register_series.call_args[0][0]["SeriesDescription"] == "new_rule"  # type: ignore
    common.monitor.send_register_task.assert_any_call(task_id, series_uid)  # type: ignore
    router.route_series.assert_called_once_with(task_id, series_uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"route_series_new_rule": True}, [f"{series_uid}#bar"], series_uid, unittest.mock.ANY)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"route_series_new_rule": True}, [f"{series_uid}#bar"], series_uid, unittest.mock.ANY, {"test_target": ["route_series_new_rule"]})  # type: ignore

    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.REGISTER, task_id, 1, "route_series_new_rule", "Registered series"),
            call(task_event.DELEGATE, task_id, 1, new_task_id, "route_series_new_rule"),
        ]
    )
    out_path = next(Path("/var/outgoing").iterdir())
    with open(out_path / "task.json") as e:
        task: Task = Task(**json.load(e))
    assert task.id == new_task_id
    assert task.dispatch.target_name == ["test_target"]  # type: ignore
    assert task.info.uid == series_uid
    assert task.info.uid_type == "series"
    assert task.info.triggered_rules["route_series_new_rule"] == True  # type: ignore
    task_will_dispatch_to(task, config, fake_process)

def test_route_series_with_bad_tags(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    new_task_id = "new-task-" + str(uuid.uuid1())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = b'{"BadTag": "\xb1d\u0000 Garbage"}'
    mock_incoming_uid(config, fs, series_uid, {}, force_tags_output=tags)

    common.monitor.configure("router", "test", config.bookkeeper)
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    parsed_tags = json.loads(tags.decode(errors="surrogateescape"))
    common.monitor.send_register_series.assert_called_once_with(parsed_tags)  # type: ignore
    common.monitor.send_register_task.assert_any_call(task_id, series_uid)  # type: ignore
    router.route_series.assert_called_once_with(task_id, series_uid)  # type: ignore
    routing.route_series.push_series_serieslevel.assert_called_once_with(task_id, {"route_series_bad_tag": True}, [f"{series_uid}#bar"], series_uid, parsed_tags)  # type: ignore
    routing.route_series.push_serieslevel_outgoing.assert_called_once_with(task_id, {"route_series_bad_tag": True}, [f"{series_uid}#bar"], series_uid, parsed_tags, {"test_target": ["route_series_bad_tag"]})  # type: ignore

    out_path = next(Path("/var/outgoing").iterdir())
    with open(out_path / "task.json") as e:
        task: Task = Task(**json.load(e))
    task_will_dispatch_to(task, config, fake_process)

def test_route_series_fail_with_bad_tags(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config(rules)
    # attach_spies(mocker)
    # mocker.patch("routing.route_series.parse_ascconv", new=lambda x: {})
    task_id = "test_task_" + str(uuid.uuid1())
    series_uid = str(uuid.uuid4())

    new_task_id = "new-task-" + str(uuid.uuid1())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)
    tags = b'{"BadTag": "dGar\u0000\xb1bage"}'
    mock_incoming_uid(config, fs, series_uid, {}, force_tags_output=tags)

    common.monitor.configure("router", "test", config.bookkeeper)
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    parsed_tags = json.loads(tags.decode(errors="surrogateescape"))
    common.monitor.send_register_series.assert_called_once_with(parsed_tags)  # type: ignore
    common.monitor.send_register_task.assert_any_call(task_id, series_uid)  # type: ignore
    router.route_series.assert_called_once_with(task_id, series_uid)  # type: ignore

    common.monitor.send_task_event.assert_any_call(task_event.DISCARD, task_id, 1, "","Discard by default. Decoding error detected: some tags were not properly decoded, likely due to a malformed DICOM file. The expected rule may therefore not have been triggered.")  # type: ignore



def test_router_no_syntax_errors():
    """Checks if router.py can be started."""
    assert router

def test_route_series_with_error(fs: FakeFilesystem, mercure_config, mocked):
    """Checks if the router can handle a series that can't be parsed by getdcmtags."""

    config = mercure_config(rules)
    
    incoming = Path(config.incoming_folder)
    dcm_file = incoming / f"bad_dicom.dcm"
    fs.create_file(dcm_file, contents="not a dicom file")
    process_dicom(str(dcm_file), "0.0.0.0","mercure","mercure")
    assert not dcm_file.exists()
    assert "Unable to read DICOM file" in (incoming / "error" / "bad_dicom.error").read_text()
    router.run_router()
    assert (Path(config.error_folder) / f"bad_dicom.dcm").exists()
    assert (Path(config.error_folder) / f"bad_dicom.error").exists()
    common.monitor.send_event.assert_called_with(m_events.PROCESSING, severity.ERROR, "Error parsing 1 incoming files") # type: ignore

def test_route_series_multiple_rules(fs: FakeFilesystem, mercure_config, mocked, fake_process):
    config = mercure_config({
        "rules": {
            "rule1": Rule(rule="@SeriesDescription@ == 'Test'", target="test_target", action="route").dict(),
            "rule2": Rule(rule="@Modality@ == 'CT'", target="test_target_2", action="route").dict()
        }
    })
    
    tags = {
        "SeriesInstanceUID": "123",
        "SeriesDescription": "Test",
        "Modality": "CT"
    }
    dcm_file, _ = mock_incoming_uid(config, fs, generate_uid(), tags, "test")
  
    router.run_router()
    
    # Assert that both rules were triggered and series routed to both targets
    routing.route_series.push_serieslevel_outgoing.assert_called() # type: ignore
    assert set(routing.route_series.push_serieslevel_outgoing.call_args[0][1].keys()) == set(["rule1", "rule2"]) # type: ignore
    assert len(list(Path(config.outgoing_folder).iterdir())) == 2

    for path in Path(config.outgoing_folder).iterdir():
        assert (path / Path(dcm_file).name).exists()