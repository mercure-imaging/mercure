"""
test_dispatch_races.py
======================

Races around the dispatcher's ``.processing`` claim and around the folder names services pick for
their destinations. The dispatcher runs as five instances against one outgoing folder, and both it
and the processor drop their results into folders that are named after the task id - so a name that
two movers compute at the same moment, and a claim that survives an error, are both reachable.
"""
import contextlib
import json
import threading
import uuid
from pathlib import Path

import webinterface.queue as queue_module
from common.constants import mercure_names
from dispatch.send import execute
from dispatch.status import is_ready_for_sending
from process.process_series import move_out_folder
from tests.testing_common import fake_check_output, make_operation_fail, stale_looks_absent
from webinterface.queue import restart_dispatch

# Build every path inside the functions, never at module import time: a pathlib path created
# before pyfakefs takes over is a real-path object, and patches aimed at the class of such an
# object miss the fake path instances the code under test works with.
def success_dir() -> Path:
    return Path("/var/success")


def error_dir() -> Path:
    return Path("/var/error")


def outgoing_dir() -> Path:
    return Path("/var/outgoing")


def processing_dir() -> Path:
    return Path("/var/processing")


def ready_outgoing_task(task_id: str, targets=("test_target",), status=None) -> Path:
    """Create a task folder in the outgoing folder that is ready for dispatching."""
    folder = outgoing_dir() / task_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "one.dcm").write_bytes(b"\x00\x00DICMfake")
    if status is None:
        status = {t: {"state": "waiting", "time": "2024-10-03 16:03:35"} for t in targets}
    task = {
        "id": task_id,
        "info": {
            "action": "route",
            "uid": "TESTUID",
            "uid_type": "series",
            "triggered_rules": {"catchall": True},
            "applied_rule": "",
            "mrn": "",
            "acc": "",
            "sender_address": "localhost",
            "mercure_version": "",
            "mercure_appliance": "test",
            "mercure_server": "testhost",
        },
        "dispatch": {
            "target_name": list(targets),
            "status": status,
            "retries": 0,
            "next_retry_at": 0,
        },
    }
    (folder / mercure_names.TASKFILE).write_text(json.dumps(task))
    return folder


def test_dispatcher_releases_its_claim_when_the_sendlog_cannot_be_removed(fs, mercure_config, mocked):
    """A dispatcher that gives up must not leave its ``.processing`` claim behind.

    ``execute()`` takes the claim that keeps the other four dispatcher instances away from a folder,
    then removes the ``sent.txt`` of a previous attempt. If that removal fails (permission problem,
    read-only mount, an NFS hiccup) the function returns *with the claim still in place*: nothing
    will ever look at that folder again, because ``is_ready_for_sending()`` refuses folders carrying
    ``.processing``. One transient I/O error turns into a permanently stuck exam that needs manual
    intervention on the shell.

    Required contract: a claim is always released when the dispatcher leaves the folder where it is.
    """
    task_id = str(uuid.uuid4())
    folder = ready_outgoing_task(task_id)
    sendlog = folder / mercure_names.SENDLOG
    sendlog.write_text("send log of a previous attempt")
    make_operation_fail(mocked, sendlog, "unlink", PermissionError(13, "Permission denied", str(sendlog)))

    execute(folder, success_dir(), error_dir(), 3, 60)

    assert not (folder / mercure_names.PROCESSING).exists(), (
        "the dispatcher left its .processing claim in the folder, so no dispatcher will ever pick "
        "this task up again"
    )
    assert is_ready_for_sending(folder), "the task must stay ready for a later dispatch attempt"


def test_dispatcher_releases_its_claim_when_dispatching_raises(fs, mercure_config, mocked):
    """Any unexpected error must leave the task retryable, not claimed.

    ``execute()`` has no protection between taking the ``.processing`` claim and the success/error
    handling at the end. A task file whose ``dispatch.status`` keys do not match
    ``dispatch.target_name`` (written by an older version, or edited through the config/task views)
    raises ``KeyError`` from the middle of the target loop, which escapes ``execute()`` - and the
    claim stays. Same dead end as above, reached through a different error path.
    """
    task_id = str(uuid.uuid4())
    folder = ready_outgoing_task(
        task_id,
        targets=("test_target", "test_target_2"),
        status={
            "test_target": {"state": "waiting", "time": "2024-10-03 16:03:35"},
            "target_removed_from_config": {"state": "waiting", "time": "2024-10-03 16:03:35"},
        },
    )
    mocked.patch("dispatch.target_types.base.check_output", side_effect=fake_check_output)

    with contextlib.suppress(Exception):
        execute(folder, success_dir(), error_dir(), 3, 60)

    assert not (folder / mercure_names.PROCESSING).exists(), (
        "an unexpected error inside execute() left the .processing claim in place; the task is "
        "claimed by a dispatcher that is long gone"
    )
    assert is_ready_for_sending(folder), "the task must stay ready for a later dispatch attempt"


def test_successful_dispatch_does_not_bury_the_task_in_an_existing_folder_of_the_same_name(
    fs, mercure_config, mocked
):
    """Two movers choosing the same destination name must not produce a nested folder.

    ``_move_sent_directory()`` asks whether ``<success>/<task_id>`` exists and, if not, hands
    ``shutil.move()`` that path. ``shutil.move()`` does *not* overwrite a directory - it moves the
    source **inside** it. A second mover that checked the name before the first one created it
    therefore produces ``<success>/<task_id>/<task_id>/``, where the queue UI and the bookkeeper can
    no longer find ``task.json``, and where the cleaner's folder bookkeeping no longer matches.

    Required contract: the destination is claimed, so a name that is taken results in a distinct
    top-level folder - never in nesting.
    """
    task_id = str(uuid.uuid4())
    folder = ready_outgoing_task(task_id)
    mocked.patch("dispatch.target_types.base.check_output", side_effect=fake_check_output)

    # Another dispatcher moved a task of the same name into the success folder after this one
    # looked. The name is taken, but this mover's snapshot says otherwise.
    clash = success_dir() / task_id
    clash.mkdir(parents=True)
    (clash / "older.dcm").write_bytes(b"previous owner")
    stale_looks_absent(mocked, clash)

    execute(folder, success_dir(), error_dir(), 3, 60)

    assert not (clash / task_id).exists(), "the dispatched task was moved INSIDE an existing folder"
    delivered = [p for p in success_dir().iterdir() if (p / mercure_names.TASKFILE).is_file()]
    assert delivered, "the dispatched task is nowhere to be found at the top level of the success folder"
    assert (delivered[0] / "one.dcm").is_file()
    assert not list(delivered[0].glob(task_id)), "the delivered folder must not contain a nested copy"
    # The folder that was already there must be untouched.
    assert (clash / "older.dcm").is_file()


def test_processor_result_move_does_not_nest_into_an_existing_folder(fs, mercure_config, mocked):
    """Same hazard on the processor side: ``move_out_folder()`` must claim its destination name."""
    task_id = str(uuid.uuid4())
    source = processing_dir() / task_id
    (source / "out").mkdir(parents=True)
    (source / "out" / "result.dcm").write_bytes(b"\x00\x00DICMresult")
    (source / "out" / mercure_names.TASKFILE).write_text("{}")
    (source / mercure_names.LOCK).touch()

    clash = success_dir() / task_id
    clash.mkdir(parents=True)
    (clash / "older.dcm").write_bytes(b"previous owner")
    stale_looks_absent(mocked, clash)

    move_out_folder(task_id, source, success_dir())

    # shutil.move() into a directory that exists puts the source INSIDE it, under its own name.
    assert not (clash / "out").exists(), "the result folder was moved INSIDE an existing folder"
    delivered = [p for p in success_dir().iterdir() if (p / "result.dcm").is_file()]
    assert delivered, "the processed results are nowhere at the top level of the success folder"
    assert not list(delivered[0].glob(task_id)), "the delivered folder must not contain a nested copy"
    assert (clash / "older.dcm").is_file()


def test_two_concurrent_ui_restarts_dispatch_the_task_only_once(fs, mercure_config, mocked):
    """Two operators (or one impatient double-click) restarting the same job must not both win.

    ``restart_dispatch()`` "locks" the folder with ``Path.touch()``, which is *not* exclusive: a
    second call sees the lock it must have failed on, sails through its own checks and moves the
    folder as well. Depending on the interleaving the second mover either buries the task inside the
    folder the first one just created (``shutil.move`` into an existing directory) or dies with
    ``FileNotFoundError`` inside the request handler.

    Required contract: the restart claim is created exclusively; the loser is told the task is not
    ready, and the task ends up exactly once in the outgoing folder, flat.
    """
    task_id = str(uuid.uuid4())
    error_folder = error_dir() / task_id
    error_folder.mkdir(parents=True)
    (error_folder / "one.dcm").write_bytes(b"\x00\x00DICMfake")
    (error_folder / mercure_names.TASKFILE).write_text(
        json.dumps(
            {
                "id": task_id,
                "info": {
                    "action": "route",
                    "uid": "TESTUID",
                    "uid_type": "series",
                    "triggered_rules": {"catchall": True},
                    "applied_rule": "",
                    "mrn": "",
                    "acc": "",
                    "sender_address": "localhost",
                    "mercure_version": "",
                    "mercure_appliance": "test",
                    "mercure_server": "testhost",
                },
                "dispatch": {
                    "target_name": ["test_target"],
                    "status": {"test_target": {"state": "error", "time": "2024-10-03 16:03:35"}},
                    "retries": 5,
                    "next_retry_at": 0,
                },
            }
        )
    )

    responses = []
    errors = []
    first_parked = threading.Event()
    second_finished = threading.Event()
    real_load = json.load
    task_file = error_folder / mercure_names.TASKFILE

    def park_first_reader(file_object, *args, **kwargs):
        """Park the first restart after its "is this task free?" check, before it claims the folder."""
        if str(getattr(file_object, "name", "")) == str(task_file) and not first_parked.is_set():
            first_parked.set()
            assert second_finished.wait(timeout=5), "second restart never finished"
        return real_load(file_object, *args, **kwargs)

    mocked.patch("json.load", side_effect=park_first_reader)

    def restart(name):
        try:
            responses.append((name, restart_dispatch(error_folder, outgoing_dir())))
        except BaseException as exc:  # noqa: BLE001 - the endpoint must not leak exceptions
            errors.append((name, exc))
        finally:
            if name == "second":
                second_finished.set()

    first = threading.Thread(target=restart, args=("first",))
    first.start()
    # The first restart has passed its readiness checks and is parked before taking the claim; the
    # second one now walks the very same checks and takes the (non-exclusive) "lock" as well.
    assert first_parked.wait(timeout=5), "the first restart never read the task file"
    second = threading.Thread(target=restart, args=("second",))
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not errors, f"restarting a job leaked an exception to the caller: {errors!r}"
    assert len([r for _, r in responses if "success" in r]) == 1, (
        f"both restarts of the same task succeeded: {responses}"
    )
    landed = outgoing_dir() / task_id
    assert landed.is_dir(), "the restarted task must be in the outgoing folder"
    assert (landed / mercure_names.TASKFILE).is_file(), "the restarted task must be flat in the outgoing folder"
    assert not (landed / task_id).exists(), "the restarted task was nested inside itself"
    assert not (landed / landed.name).exists()
