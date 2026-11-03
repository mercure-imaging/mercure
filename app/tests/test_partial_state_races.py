"""
test_partial_state_races.py
===========================

What happens when a hand-off between two services fails part-way through.

Every hand-off in mercure - router to processor, router to dispatcher, router to study buffer,
processor to success/error folder - copies or moves a folder and then removes the marker that kept
the next service away from it. The marker is a :class:`common.helper.FileLock`, whose destructor
removes the lock file, and the code paths that fill a folder do not check whether the copy actually
finished. The two facts combine into the same shape: **a half-filled folder becomes visible to the
next service exactly when the transfer failed**, and the next service has no way of knowing that
files are missing. A truncated series is dispatched to the target, or processed, and reported as a
success. The originals are frequently deleted as well, because the router cleans up the incoming
folder whether or not the series made it out of it.

The contract these tests pin: a folder that is not completely written is either not visible or
permanently claimed, and a failed hand-off never destroys the only copy of a study.
"""
import gc
import json
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
from common.constants import mercure_names
from common.types import Module, Rule
from dispatch.status import is_ready_for_sending
from docker.models.containers import ContainerCollection
from docker.models.images import ImageCollection
from process import processor
from process.status import is_ready_for_processing
from routing import route_series, route_studies

from .test_processor import config_partial, create_and_route
from .testing_common import (FakeDockerContainer, FakeImageContainer, make_fake_processor, make_move_fail,
                             make_second_file_fail)

module_config: Dict = {"modules": {"test_module": Module(docker_tag="busybox:stable", settings={}).dict()}}

process_rule: Dict = {
    **module_config,
    "rules": {
        "proc": Rule(
            rule="True",
            action="process",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    },
}

route_two_targets_rule: Dict = {
    **module_config,
    "rules": {
        "route2": Rule(
            rule="True",
            action="route",
            target=["test_target", "test_target_2"],
            action_trigger="series",
        ).dict()
    },
}

study_rule: Dict = {
    **module_config,
    "rules": {
        "study_route": Rule(
            rule="True",
            action="route",
            target="test_target",
            action_trigger="study",
            study_trigger_condition="timeout",
        ).dict()
    },
}


def deliver_series(config, series_uid: str, study_uid: str, description: str, count: int = 2) -> List[str]:
    """Stand in for the receiver: write a series of ``count`` slices into the incoming folder."""
    folder = Path(config.incoming_folder) / series_uid
    folder.mkdir(parents=True, exist_ok=True)
    stems = []
    for index in range(1, count + 1):
        stem = f"{series_uid}#slice{index}"
        (folder / (stem + mercure_names.DCM)).write_bytes(b"\x00\x00DICMfake")
        tags = {
            "StudyInstanceUID": study_uid,
            "SeriesInstanceUID": series_uid,
            "SeriesDescription": description,
        }
        (folder / (stem + mercure_names.TAGS)).write_text(json.dumps(tags))
        stems.append(stem)
    return stems


def files_named(root: str, name: str) -> List[Path]:
    return [p for p in Path(root).rglob(name) if p.is_file()]


def assert_nothing_lost(stems: List[str]) -> None:
    for stem in stems:
        for suffix in (mercure_names.DCM, mercure_names.TAGS):
            assert files_named("/var", stem + suffix), (
                f"{stem}{suffix} no longer exists anywhere: the router deleted the incoming folder "
                f"after a hand-off that never completed"
            )


def assert_never_partial(stems: List[str]) -> None:
    """No folder anywhere may hold part of the series without holding all of it.

    This is the invariant a hand-off has to preserve. The next service cannot tell a complete series
    from a truncated one: :func:`dispatch.status.is_ready_for_sending` asks for a valid ``task.json``
    and the absence of ``.lock``/``.processing``/``.error``, and
    :func:`process.status.is_ready_for_processing`` asks for the absence of those markers and *any*
    ``*.dcm``. Neither knows how many files the series should have, so a folder that is half filled
    is dispatched, or processed, and reported as a success.
    """
    bases = ["/var/incoming", "/var/processing", "/var/outgoing", "/var/studies", "/var/success", "/var/error"]
    for base in bases:
        root = Path(base)
        if not root.exists():
            continue
        for folder in [root] + [f for f in root.rglob("*") if f.is_dir()]:
            present = [stem for stem in stems if (folder / (stem + mercure_names.DCM)).exists()]
            if 0 < len(present) < len(stems):
                pytest.fail(
                    f"{folder} holds {len(present)} of {len(stems)} slices of the series "
                    f"({sorted(p.name for p in folder.iterdir())}): a service that picks this folder up "
                    f"cannot tell it is incomplete"
                )


def test_failed_hand_off_to_the_processor_does_not_lose_the_series(fs, mercure_config, mocked):
    """A series that did not make it into the processing folder must not be deleted.

    ``push_serieslevel_processing()`` copies the files and, on failure, returns False - which nobody
    looks at. ``route_series()`` then unlocks the task folder and removes the incoming directory
    with ``shutil.rmtree()``, including the slices that never left it.
    """
    config = mercure_config(process_rule)
    series_uid, study_uid = str(uuid.uuid4()), str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")

    # The second slice cannot be written: the hand-off stops after the first one.
    make_second_file_fail(mocked, "slice2.dcm")

    route_series.route_series("task-partial-processing", series_uid)

    assert_nothing_lost(stems)


def test_half_filled_processing_folder_is_not_picked_up(fs, mercure_config, mocked):
    """A partially written processing folder must not be left for the processor.

    ``push_files()`` returns False on the first failed file and ``push_serieslevel_processing()``
    bails out - leaving the folder it had half filled, whose ``FileLock`` is a local variable that
    disappears as the stack unwinds. Whether the lock is still there at that point depends on whether
    anything happens to hold a reference to that frame, which is not a safety property.
    """
    config = mercure_config(process_rule)
    series_uid, study_uid = str(uuid.uuid4()), str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")

    make_second_file_fail(mocked, "slice2.dcm")
    route_series.route_series("task-partial-processing", series_uid)
    # The router's own error handling drops the exception; releasing it is what frees the lock.
    gc.collect()

    assert_never_partial(stems)
    assert_nothing_lost(stems)


def test_half_filled_outgoing_folder_is_not_dispatched(fs, mercure_config, mocked):
    """A partially copied outgoing folder must never be sent to a target.

    ``push_serieslevel_outgoing()`` raises when a copy fails, leaving the target folder with part of
    the series. Its lock is freed on the way out, and ``is_ready_for_sending()`` only requires a
    valid ``task.json`` and the absence of markers - it does not, and cannot, know how many files the
    series should have. The dispatcher sends the truncated exam and reports success.
    """
    config = mercure_config(route_two_targets_rule)
    series_uid, study_uid = str(uuid.uuid4()), str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")

    make_second_file_fail(mocked, "slice2.dcm")
    try:
        route_series.route_series("task-partial-outgoing", series_uid)
    except Exception:
        pass  # the router does report the failure; the state it leaves behind is what matters here
    gc.collect()

    assert_never_partial(stems)
    assert_nothing_lost(stems)


def test_partially_buffered_study_is_not_routed(fs, mercure_config, mocked):
    """A study whose series was only partly buffered must not be completed and dispatched.

    ``push_series_studylevel()`` ignores the return value of ``push_files()`` completely: the study
    folder is left holding one of two slices, its lock is released at the end of the loop, and the
    next router pass treats the study as complete (the test configuration's completion timeout lies
    in the past) and dispatches it. The missing slice is deleted with the incoming folder.
    """
    config = mercure_config(study_rule)
    series_uid, study_uid = str(uuid.uuid4()), str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")

    make_second_file_fail(mocked, "slice2.dcm")
    try:
        route_series.route_series("task-partial-study", series_uid)
    except Exception:
        pass
    gc.collect()

    assert_never_partial(stems)
    assert_nothing_lost(stems)


@pytest.mark.asyncio
async def test_processor_keeps_results_when_the_move_to_the_success_folder_fails(
    fs, mercure_config, mocked
):
    """A processor whose result move fails must not delete the task.

    ``process_series()`` finishes with ``move_results()`` followed by ``shutil.rmtree(folder)`` -
    unconditionally. ``move_out_folder()`` swallows any error from the move (disk full, failing
    mount) and returns ``None``, so the cleanup runs on a folder whose results never left it: the
    only copy of the processed exam is destroyed by a transient I/O error, and the task is reported
    as processed.
    """
    config = mercure_config({"process_runner": "docker", **config_partial})
    task_id = str(uuid.uuid1())
    files, new_task_id = create_and_route(fs, mocked, task_id, config)
    task_folder = next(Path("/var/processing").iterdir())

    fake_run = mocked.Mock(return_value=FakeDockerContainer(),
                           side_effect=make_fake_processor(fs, mocked, False))
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    mocked.patch.object(ImageCollection, "pull", new=mocked.Mock(return_value=FakeImageContainer()))

    # The hand-over to the success folder fails, as it would on a full or failing volume.
    make_move_fail(mocked, Path(config.success_folder) / task_folder.name)

    await processor.run_processor()

    delivered = [p for p in Path(config.success_folder).iterdir() if (p / mercure_names.TASKFILE).exists()]
    if not delivered:
        assert task_folder.is_dir(), (
            "the results never reached the success folder, but the processor deleted the task "
            "anyway: the processed exam is gone"
        )
        assert files_named(str(task_folder), "*.dcm") or files_named(str(task_folder), "result.dcm")
        # And it must stay out of reach of the other processor instances.
        assert not is_ready_for_processing(task_folder), (
            "the task folder whose results could not be moved is offered to another processor"
        )


def test_partial_study_buffer_does_not_record_the_series_as_received(fs, mercure_config, mocked):
    """The study task file must not claim a series that was only partly buffered.

    ``update_study_task()``/``create_study_task()`` record the series in the study task file before
    the files are pushed, and the push result is ignored. A study that completes on "received
    series" can therefore fire for a series whose images are not there.
    """
    config = mercure_config(study_rule)
    series_uid, study_uid = str(uuid.uuid4()), str(uuid.uuid4())
    stems = deliver_series(config, series_uid, study_uid, "series A")

    make_second_file_fail(mocked, "slice2.dcm")
    try:
        route_series.route_series("task-partial-study", series_uid)
    except Exception:
        pass
    gc.collect()

    for folder in [f for f in Path("/var/studies").iterdir() if f.is_dir()]:
        present = {p.name for p in folder.iterdir() if p.is_file()}
        recorded = []
        task_file = folder / mercure_names.TASKFILE
        if task_file.is_file():
            recorded = json.loads(task_file.read_text()).get("study", {}).get("received_series") or []
        if "series A" in recorded:
            buffered_slices = len([name for name in present if name.endswith(mercure_names.DCM)])
            assert buffered_slices == len(stems), (
                f"the study task file lists 'series A' as received, but only {buffered_slices} of "
                f"{len(stems)} slices are in {folder}"
            )
