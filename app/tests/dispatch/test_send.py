import json
import time
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import call

import common
from common.constants import mercure_names
from common.monitor import m_events, severity, task_event
from dispatch.send import execute, is_ready_for_sending

dummy_info = {
    "action": "route",
    "uid": "",
    "uid_type": "series",
    "triggered_rules": "",
    "mrn": "",
    "acc": "",
    "sender_address": "localhost",
    "mercure_version": "",
    "mercure_appliance": "",
    "mercure_server": "",
}


def test_execute_successful_case(fs, mocked):
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {
        "id": "task_id",
        "info": dummy_info,
        "dispatch": {"target_name": "test_target"},
    }
    fs.create_file("/var/data/source/a/" + mercure_names.TASKFILE, contents=json.dumps(target))

    mocked.patch("dispatch.target_types.base.check_output", return_value="Success")
    execute(Path(source), Path(success), Path(error), 1, 1)

    assert not Path(source).exists()
    assert (Path(success) / "a").exists()
    assert (Path(success) / "a" / mercure_names.TASKFILE).exists()
    assert (Path(success) / "a" / "one.dcm").exists()


def test_execute_error_case(fs, mocked):
    """This case simulates a dcmsend error. After that the retry counter
    gets increased but the data stays in the folder."""
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_dir(error)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {
        "id": "task_id",
        "info": dummy_info,
        "dispatch": {"target_name": "test_target"},
    }
    fs.create_file("/var/data/source/a/" + mercure_names.TASKFILE, contents=json.dumps(target))

    mocked.patch("dispatch.target_types.base.check_output", side_effect=CalledProcessError(1, cmd="None"))
    execute(Path(source), Path(success), Path(error), 10, 1)

    common.monitor.send_event.assert_has_calls(  # type: ignore
        [
            call(m_events.PROCESSING, severity.WARNING, "Missing information for folder /var/data/source/a"),
            call(
                m_events.PROCESSING,
                severity.ERROR,
                """Failed command:
 ['dcmsend', '0.0.0.0', '11112', '+sd', '/var/data/source/a', '-aet', '-aec', 'foo', '-nuc', '+sp', '*.dcm', '-to', '60', '+crf', '/var/data/source/a/sent.txt'] 
because of EXITCODE_COMMANDLINE_SYNTAX_ERROR""",  # noqa: E501,W291
            ),
            call(
                m_events.PROCESSING,
                severity.ERROR,
                "Error sending uid uid-missing in task task_id to test_target:\n EXITCODE_COMMANDLINE_SYNTAX_ERROR",
            ),
        ]
    )
    common.monitor.send_task_event.assert_has_calls(  # type: ignore
        [
            call(task_event.UNKNOWN, "task_id", 0, "", "Missing information for folder /var/data/source/a"),
            call(task_event.DISPATCH_BEGIN, "task_id", 1, "test_target", "Routing job running"),
            call(
                task_event.ERROR,
                "task_id",
                0,
                "",
                """Failed command:
 ['dcmsend', '0.0.0.0', '11112', '+sd', '/var/data/source/a', '-aet', '-aec', 'foo', '-nuc', '+sp', '*.dcm', '-to', '60', '+crf', '/var/data/source/a/sent.txt'] 
because of EXITCODE_COMMANDLINE_SYNTAX_ERROR""",  # noqa: E501,W291
            ),
            call(
                task_event.ERROR,
                "task_id",
                0,
                "test_target",
                "Error sending uid uid-missing in task task_id to test_target:\n EXITCODE_COMMANDLINE_SYNTAX_ERROR",
            ),
        ]
    )  # print(common.monitor.send_event.call_args_list)
    with open("/var/data/source/a/" + mercure_names.TASKFILE, "r") as f:
        modified_target = json.load(f)

    assert Path(source).exists()
    assert (Path(source) / mercure_names.TASKFILE).exists()
    assert (Path(source) / "one.dcm").exists()
    assert modified_target["dispatch"]["retries"] == 1
    assert is_ready_for_sending(source)


def test_execute_error_case_max_retries_reached(fs, mocked):
    """This case simulates a dcmsend error. Max number of retries is reached
    and the data is moved to the error folder.
    """
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_dir(error)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {
        "id": "task_id",
        "info": dummy_info,
        "dispatch": {
            "target_name": "test_target",
            "retries": 5,
        },
    }
    fs.create_file("/var/data/source/a/" + mercure_names.TASKFILE, contents=json.dumps(target))

    mocked.patch("dispatch.target_types.base.check_output", side_effect=CalledProcessError(1, cmd="None"))
    execute(Path(source), Path(success), Path(error), 5, 1)

    with open("/var/data/error/a/" + mercure_names.TASKFILE, "r") as f:
        modified_target = json.load(f)

    assert (Path(error) / "a" / mercure_names.TASKFILE).exists()
    assert (Path(error) / "a" / "one.dcm").exists()
    assert modified_target["dispatch"]["retries"] == 5


def test_execute_error_case_delay_is_not_over(fs, mocked):
    """This case simulates a dcmsend error. Should not run anything because
    the next_retry_at time has not been passed.
    """
    source = "/var/data/source/a"
    success = "/var/data/success/"
    error = "/var/data/error"

    fs.create_dir(source)
    fs.create_dir(success)
    fs.create_dir(error)
    fs.create_file("/var/data/source/a/one.dcm")
    target = {
        "info": dummy_info,
        "dispatch": {
            "target_name": "test_target",
            "retries": 5,
            "next_retry_at": time.time() + 500,
        },
    }
    fs.create_file("/var/data/source/a/" + mercure_names.TASKFILE, contents=json.dumps(target))
    mock = mocked.patch("dispatch.target_types.base.check_output", side_effect=CalledProcessError(1, cmd="None"))
    execute(Path(source), Path(success), Path(error), 5, 1)
    assert not mock.called
