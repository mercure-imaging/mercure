"""
test_race_review.py
===================

Failing tests from the review of the race-condition commits (7694a80..6bee53a). Each test pins one
problem that is either introduced by those commits or left in place by them.
"""
import json
import shutil
import uuid
from pathlib import Path

import pytest
from common.constants import mercure_names
from docker.models.containers import ContainerCollection
from docker.models.images import ImageCollection
from process import processor
from process.status import is_ready_for_processing
from routing import route_series
from webinterface.queue import restart_processing_task

from .test_concurrency_races import receive_series, study_rules
from .test_partial_state_races import deliver_series, route_two_targets_rule
from .test_processor import config_partial, create_and_route
from .testing_common import FakeDockerContainer, FakeImageContainer, make_fake_processor


# ---------------------------------------------------------------------------------------------
# NEW: 7694a80 moved backup_input_images() after the .processing claim, so the claim marker is
# backed up into as_received/, and the UI restart copies it back -> restarted task is never picked up.
# ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restarted_processing_task_is_picked_up_again(fs, mercure_config, mocked):
    config = mercure_config({"process_runner": "docker", **config_partial})
    create_and_route(fs, mocked, str(uuid.uuid1()), config)
    task_folder = next(Path(config.processing_folder).iterdir())
    task_id = task_folder.name

    # The module fails, so the task lands in the error folder with its as_received backup.
    mocked.patch.object(ContainerCollection, "run", new=mocked.Mock(
        return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs, mocked, True)))
    mocked.patch.object(ImageCollection, "pull", new=mocked.Mock(return_value=FakeImageContainer()))
    await processor.run_processor()

    failed = Path(config.error_folder) / task_id
    assert (failed / "as_received").is_dir()
    assert not (failed / "as_received" / mercure_names.PROCESSING).exists(), (
        "the processor's .processing claim was backed up into as_received/"
    )

    result = restart_processing_task(task_id, failed, is_error=True)
    assert result.get("success"), result
    restarted = Path(config.processing_folder) / task_id
    assert is_ready_for_processing(restarted), (
        f"restarted task is not eligible for processing: {sorted(p.name for p in restarted.iterdir())}"
    )


# ---------------------------------------------------------------------------------------------
# NEW (0732bfc + 2da1cae): mkdir() of the study folder and taking its .lock are two steps. A second
# router can take the lock between them, decides "not first series", pushes its files (2da1cae now
# pushes BEFORE recording), then update_study_task() fails because task.json does not exist yet.
# Nothing rolls the files back: they sit in the study unrecorded and the incoming copy is gone.
# ---------------------------------------------------------------------------------------------
def test_second_router_winning_the_lock_before_the_creator_does_not_strand_its_series(
    fs, mercure_config, mocked
):
    config = mercure_config(study_rules)
    study_uid = str(uuid.uuid4())
    # Router A has just mkdir()'d the study folder but has not locked it / written task.json yet.
    study_folder = Path(config.studies_folder) / f"{study_uid}#study_route"
    study_folder.mkdir()

    series_b = str(uuid.uuid4())
    stem_b, _ = receive_series(config, series_b, study_uid, "series B")
    route_series.route_series("task-b", series_b)

    in_incoming = (Path(config.incoming_folder) / series_b / f"{stem_b}.dcm").exists()
    recorded = False
    task_file = study_folder / mercure_names.TASKFILE
    if task_file.exists():
        recorded = "series B" in (json.loads(task_file.read_text())["study"].get("received_series") or [])
    assert in_incoming or recorded, (
        "series B was moved into the study folder but never recorded there, and is no longer in the "
        f"incoming folder; study folder holds {sorted(p.name for p in study_folder.iterdir())}"
    )


# ---------------------------------------------------------------------------------------------
# NEW (2da1cae): a failed hand-off keeps the incoming series for "another attempt", but the retry
# re-runs every hand-off, including the ones that already succeeded -> duplicate dispatches.
# ---------------------------------------------------------------------------------------------
def test_retrying_a_partially_failed_hand_off_does_not_dispatch_twice(fs, mercure_config, mocked):
    config = mercure_config(route_two_targets_rule)
    series_uid = str(uuid.uuid4())
    deliver_series(config, series_uid, str(uuid.uuid4()), "series A")

    # Pass 1: test_target (copied) succeeds, test_target_2 (last target -> moved) fails.
    real_move = shutil.move
    disk_full = [True]

    def failing_move(src, dst, *args, **kwargs):
        if disk_full[0] and str(dst).startswith(config.outgoing_folder):
            raise OSError(28, "No space left on device", str(dst))
        return real_move(src, dst, *args, **kwargs)

    mocked.patch("shutil.move", side_effect=failing_move)
    route_series.route_series("task-pass-1", series_uid)
    disk_full[0] = False
    assert (Path(config.incoming_folder) / series_uid).is_dir(), "series should be kept for a retry"

    # Pass 2: the transient error is gone.
    route_series.route_series("task-pass-2", series_uid)

    per_target = {"test_target": 0, "test_target_2": 0}
    for folder in Path(config.outgoing_folder).iterdir():
        task = json.loads((folder / mercure_names.TASKFILE).read_text())
        for t in task["dispatch"]["target_name"]:
            per_target[t] += 1
    assert per_target == {"test_target": 1, "test_target_2": 1}, (
        f"retry re-sent the hand-offs that had already succeeded: {per_target}"
    )


# ---------------------------------------------------------------------------------------------
# INCOMPLETE FIX (c8bba02): an unreadable task is skipped, but never quarantined. It stays in the
# processing folder forever and re-logs (and re-reports to the bookkeeper) an error every scan.
# ---------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unreadable_task_is_moved_out_of_the_processing_folder(fs, mercure_config, mocked):
    config = mercure_config({"process_runner": "docker", **config_partial})
    poison = Path(config.processing_folder) / "poison-task"
    poison.mkdir()
    (poison / "x.dcm").write_bytes(b"\x00\x00DICMfake")
    (poison / mercure_names.TASKFILE).write_text("{ not json")

    for counter in range(3):
        await processor.search_folder(counter)

    assert not poison.exists(), (
        "an unreadable task is skipped on every scan but never moved to the error folder"
    )
    assert any(Path(config.error_folder).iterdir())


# ---------------------------------------------------------------------------------------------
# C, other shapes: a series-level failure must also roll back processing and study hand-offs of
# the same series, so that the retry neither starts a second job nor records the series twice.
# ---------------------------------------------------------------------------------------------
def _fail_outgoing_once(mocked, config):
    real_move, real_copy = shutil.move, shutil.copy
    disk_full = [True]

    def guard(real):
        def op(src, dst, *args, **kwargs):
            if disk_full[0] and str(dst).startswith(config.outgoing_folder):
                raise OSError(28, "No space left on device", str(dst))
            return real(src, dst, *args, **kwargs)
        return op

    mocked.patch("shutil.move", side_effect=guard(real_move))
    mocked.patch("shutil.copy", side_effect=guard(real_copy))
    return disk_full


def test_retry_after_failed_routing_does_not_start_a_second_processing_job(fs, mercure_config, mocked):
    from common.types import Rule
    from .test_partial_state_races import module_config
    config = mercure_config({
        **module_config,
        "rules": {
            "proc": Rule(rule="True", action="process", action_trigger="series",
                         processing_module="test_module").dict(),
            "route": Rule(rule="True", action="route", target="test_target", action_trigger="series").dict(),
        },
    })
    series_uid = str(uuid.uuid4())
    deliver_series(config, series_uid, str(uuid.uuid4()), "series A")

    disk_full = _fail_outgoing_once(mocked, config)
    route_series.route_series("task-pass-1", series_uid)
    disk_full[0] = False
    assert list(Path(config.processing_folder).iterdir()) == [], "the processing hand-off was not rolled back"
    route_series.route_series("task-pass-2", series_uid)

    assert len(list(Path(config.processing_folder).iterdir())) == 1
    assert len(list(Path(config.outgoing_folder).iterdir())) == 1
    assert not (Path(config.incoming_folder) / series_uid).exists()


def test_retry_after_failed_routing_does_not_record_the_series_twice_in_the_study(fs, mercure_config, mocked):
    from common.types import Rule
    from .test_partial_state_races import module_config
    config = mercure_config({
        **module_config,
        "rules": {
            "study": Rule(rule="True", action="route", target="test_target", action_trigger="study",
                          study_trigger_condition="timeout").dict(),
            "route": Rule(rule="True", action="route", target="test_target", action_trigger="series").dict(),
        },
    })
    study_uid = str(uuid.uuid4())
    # An earlier series already started the study.
    first = str(uuid.uuid4())
    deliver_series(config, first, study_uid, "series 0")
    route_series.route_series("task-0", first)
    study_folder = next(Path(config.studies_folder).iterdir())
    before = (study_folder / mercure_names.TASKFILE).read_bytes()
    for p in Path(config.outgoing_folder).iterdir():
        shutil.rmtree(p)

    series_uid = str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")
    disk_full = _fail_outgoing_once(mocked, config)
    route_series.route_series("task-pass-1", series_uid)
    disk_full[0] = False
    assert (study_folder / mercure_names.TASKFILE).read_bytes() == before
    assert not any((study_folder / (s + mercure_names.DCM)).exists() for s in stems)
    assert not (study_folder / mercure_names.LOCK).exists()

    route_series.route_series("task-pass-2", series_uid)
    received = json.loads((study_folder / mercure_names.TASKFILE).read_text())["study"]["received_series"]
    assert received == ["series 0", "series A"]
    assert len(list(Path(config.outgoing_folder).iterdir())) == 1


def test_file_lock_is_not_released_by_garbage_collection(fs):
    import gc
    from common.helper import FileLock
    Path("/locks").mkdir()
    FileLock(Path("/locks/a.lock"))
    gc.collect()
    assert Path("/locks/a.lock").exists()


def test_file_lock_keep_on_error_keeps_the_lock_when_the_block_raises(fs):
    from common.helper import FileLock
    Path("/locks").mkdir()
    with pytest.raises(RuntimeError):
        with FileLock(Path("/locks/a.lock"), keep_on_error=True):
            raise RuntimeError
    assert Path("/locks/a.lock").exists()
    with pytest.raises(RuntimeError):
        with FileLock(Path("/locks/b.lock")):
            raise RuntimeError
    assert not Path("/locks/b.lock").exists()


# ---------------------------------------------------------------------------------------------
# Quarantine of tasks that can never be processed.
# ---------------------------------------------------------------------------------------------
def _poison(config, name="poison-task") -> Path:
    folder = Path(config.processing_folder) / name
    folder.mkdir()
    (folder / "x.dcm").write_bytes(b"\x00\x00DICMfake")
    (folder / mercure_names.TASKFILE).write_text("{ not json")
    return folder


@pytest.mark.asyncio
async def test_unreadable_task_is_reported_once(fs, mercure_config, mocked):
    import common.monitor as monitor
    config = mercure_config({"process_runner": "docker", **config_partial})
    _poison(config)
    for counter in range(3):
        await processor.search_folder(counter)
    reports = [c for c in monitor.send_event.call_args_list if "poison-task" in str(c)]  # type: ignore
    assert len(reports) == 1
    moved = Path(config.error_folder) / "poison-task"
    assert (moved / "as_received" / "x.dcm").exists(), "restart needs the as_received backup"
    assert not (moved / mercure_names.PROCESSING).exists()
    assert not (moved / "as_received" / mercure_names.PROCESSING).exists()


def test_claimed_task_is_not_quarantined(fs, mercure_config):
    config = mercure_config({"process_runner": "docker", **config_partial})
    folder = _poison(config)
    (folder / mercure_names.PROCESSING).touch()
    assert processor.quarantine_task(folder, "test") is False
    assert folder.exists()


def test_task_that_became_readable_is_not_quarantined(fs, mercure_config, mocked):
    config = mercure_config({"process_runner": "docker", **config_partial})
    create_and_route(fs, mocked, str(uuid.uuid1()), config)
    folder = next(Path(config.processing_folder).iterdir())
    assert processor.quarantine_task(folder, "stale scan said unreadable") is False
    assert folder.exists() and not (folder / mercure_names.PROCESSING).exists()


def test_failed_quarantine_move_leaves_the_task_in_place_unclaimed(fs, mercure_config, mocked):
    config = mercure_config({"process_runner": "docker", **config_partial})
    folder = _poison(config)
    mocked.patch.object(processor, "move_into_folder", side_effect=OSError(5, "Input/output error"))
    assert processor.quarantine_task(folder, "test") is False
    assert (folder / "x.dcm").exists()
    assert not (folder / mercure_names.PROCESSING).exists()


@pytest.mark.asyncio
async def test_permission_error_on_task_file_is_skipped_not_quarantined(fs, mercure_config, mocked):
    config = mercure_config({"process_runner": "docker", **config_partial})
    folder = _poison(config)
    real_open = open

    def guarded_open(path, *args, **kwargs):
        if str(path) == str(folder / mercure_names.TASKFILE):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *args, **kwargs)

    mocked.patch("builtins.open", side_effect=guarded_open)
    await processor.search_folder(0)
    assert folder.exists()


@pytest.mark.asyncio
async def test_task_with_missing_rule_is_quarantined_and_can_be_restarted(fs, mercure_config, mocked):
    import common.config as common_config
    config = mercure_config({"process_runner": "docker", **config_partial})
    create_and_route(fs, mocked, str(uuid.uuid1()), config)
    folder = next(Path(config.processing_folder).iterdir())

    # The rule is renamed while the task is still queued.
    rule = common_config.mercure.rules.pop("catchall")
    await processor.search_folder(0)
    moved = Path(config.error_folder) / folder.name
    assert not folder.exists() and moved.is_dir()

    # Restart is refused while the rule is missing, and works once it is back.
    assert "error" in restart_processing_task(folder.name, moved, is_error=True)
    common_config.mercure.rules["catchall"] = rule
    result = restart_processing_task(folder.name, moved, is_error=True)
    assert result.get("success"), result
    assert is_ready_for_processing(Path(config.processing_folder) / folder.name)


# ---------------------------------------------------------------------------------------------
# HandOffs.commit(): new tasks are registered while their folders are still locked, and a failing
# announcement neither skips the others nor leaves the series in the incoming folder for a resend.
# ---------------------------------------------------------------------------------------------
def test_new_tasks_are_registered_before_their_folders_are_unlocked(fs, mercure_config, mocked):
    config = mercure_config(route_two_targets_rule)
    series_uid = str(uuid.uuid4())
    deliver_series(config, series_uid, str(uuid.uuid4()), "series A")

    locked_at_registration = []

    def register(new_task_id, *args, **kwargs):
        folder = Path(config.outgoing_folder) / new_task_id
        locked_at_registration.append((folder / mercure_names.LOCK).exists())

    mocked.patch("common.monitor.send_register_task", side_effect=register)
    route_series.route_series("task-1", series_uid)

    assert len(locked_at_registration) == 3  # the incoming task + one per target
    assert locked_at_registration[1:] == [True, True]
    assert not list(Path(config.outgoing_folder).glob("*/" + mercure_names.LOCK))


def test_failing_announcement_does_not_cause_a_resend(fs, mercure_config, mocked):
    config = mercure_config(route_two_targets_rule)
    series_uid = str(uuid.uuid4())
    deliver_series(config, series_uid, str(uuid.uuid4()), "series A")

    registered = []

    def register(new_task_id, *args, **kwargs):
        if len(args) >= 2:  # a hand-off (has a parent task), not the incoming series itself
            registered.append(new_task_id)
            if len(registered) == 1:
                raise RuntimeError("bookkeeper client blew up")

    mocked.patch("common.monitor.send_register_task", side_effect=register)
    route_series.route_series("task-1", series_uid)

    assert len(registered) == 2, "the announcements after the failing one were skipped"
    assert not (Path(config.incoming_folder) / series_uid).exists(), "series left behind for a resend"

    route_series.route_series("task-2", series_uid)
    assert len(list(Path(config.outgoing_folder).iterdir())) == 2
    assert not list(Path(config.outgoing_folder).glob("*/" + mercure_names.LOCK))
