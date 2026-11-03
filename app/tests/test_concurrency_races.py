"""
test_concurrency_races.py
=========================

More races in mercure's on-disk state machine, in the same family as the ones fixed by
``7694a80`` (two processors claiming one task), ``c8bba02`` (one unparsable task stalling the
queue) and ``b194e12`` (torn task/config files).

mercure runs *several instances of every service against the same folders* (the integration
harness starts ``router`` x5, ``dispatcher`` x5 and ``processor`` x2; production systemd/docker
units do the same). Ownership is passed between those processes purely through marker files
(``.lock``, ``.processing``), so a marker that one component writes under a different name than
the one its counterpart checks, or a marker that a component ignores altogether, means two
processes can work on the same folder at the same time.

Each test below states the invariant a reader/writer must be able to rely on, and drives two
services through the interleaving that breaks it. They are expected to FAIL until the races are
fixed; see the module-level README section in the accompanying report.
"""
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import cleaner
import pytest
from common.constants import mercure_names
from common.types import Rule, Task
from pyfakefs.fake_filesystem import FakeFilesystem
from routing import route_series, route_studies
from .testing_common import stale_looks_absent

# One study-level routing rule: every series joins the study buffer, the study completes on
# timeout (the test configuration sets study_complete_trigger to the past, so a buffered study
# is immediately ready for routing).
study_rules: Dict = {
    "rules": {
        "study_route": Rule(
            rule="True",
            action="route",
            target="test_target",
            action_trigger="study",
            study_trigger_condition="timeout",
        ).dict()
    }
}


def receive_series(config, series_uid: str, study_uid: str, description: str) -> Tuple[str, Dict[str, str]]:
    """Stand in for the receiver: place one series (``.dcm`` + ``.tags``) in the incoming folder.

    Returns the file stem the router works with and the tag list, exactly as
    ``getdcmtags`` hands them over.
    """
    series_folder = Path(config.incoming_folder) / series_uid
    series_folder.mkdir(parents=True, exist_ok=True)
    stem = f"{series_uid}#slice"
    (series_folder / (stem + mercure_names.DCM)).write_bytes(b"\x00\x00DICMfake")
    tags = {
        "StudyInstanceUID": study_uid,
        "SeriesInstanceUID": series_uid,
        "SeriesDescription": description,
    }
    (series_folder / (stem + mercure_names.TAGS)).write_text(json.dumps(tags))
    return stem, tags


def buffer_series_in_study(config, series_uid: str, study_uid: str, description: str, task_id: str) -> Path:
    """Run the router's study-level hand-off for one already-received series.

    Returns the study folder the series was buffered into (``<studyUID>#<rule>``).
    """
    stem, tags = receive_series(config, series_uid, study_uid, description)
    route_series.push_series_studylevel(task_id, {"study_route": True}, [stem], series_uid, tags)
    return Path(config.studies_folder) / f"{study_uid}#study_route"


def files_named(root: str, name: str) -> List[Path]:
    return [p for p in Path(root).rglob(name) if p.is_file()]


def test_losing_the_study_folder_creation_race_still_delivers_the_series(
    fs: FakeFilesystem, mercure_config, mocked
) -> None:
    """Two routers buffer the first two series of a study: neither series may be lost.

    ``push_series_studylevel`` decides "is this the first series of the study?" with
    ``if not target_folder.exists(): mkdir()``. With five routers running, the loser of that
    race gets ``FileExistsError`` out of ``mkdir()``, treats it as a fatal error
    (``logger.error(...); continue``) and never buffers its series. Nothing else re-offers it:
    ``route_series`` ends with ``shutil.rmtree(base_dir)``, which deletes the freshly received
    DICOMs from the incoming folder. One exam silently disappears.

    Required contract: losing the folder-creation race means "the folder is already there, this
    is not the first series" - the series must still be added to the study.
    """
    config = mercure_config(study_rules)
    study_uid = str(uuid.uuid4())

    # Router A wins: its series creates the study folder.
    series_a = str(uuid.uuid4())
    study_folder = buffer_series_in_study(config, series_a, study_uid, "series A", "task-a")
    assert study_folder.is_dir()

    # Router B already scanned the studies folder and still believes it does not exist. It
    # processes the second series of the very same study.
    series_b = str(uuid.uuid4())
    stem_b, tags_b = receive_series(config, series_b, study_uid, "series B")
    stale_looks_absent(mocked, study_folder)

    # Full router pass for series B, including the trailing rmtree() of the incoming folder.
    route_series.route_series("task-b", series_b)

    # Nothing may be lost: the DICOM has to exist somewhere after the router is done with it.
    assert files_named("/var", f"{stem_b}.dcm"), (
        f"series B was silently deleted: {series_b} is gone from /var after the router that lost "
        f"the study-folder creation race bailed out and rmtree'd the incoming folder"
    )
    # The second series must have reached the study buffer alongside the first one.
    buffered = {p.name for p in study_folder.iterdir() if p.is_file()}
    assert f"{stem_b}.dcm" in buffered, (
        f"series B did not join the study: study folder holds {buffered}"
    )
    # ... and it must be recorded in the study task file, otherwise a study that completes on
    # "received series" will never fire.
    task = Task.from_file(study_folder / mercure_names.TASKFILE)
    assert "series B" in (task.study.received_series or [])


def test_series_arriving_while_the_study_is_being_routed_is_not_deleted(
    fs: FakeFilesystem, mercure_config, mocked
) -> None:
    """A study routing claim must keep series-level routers out of the study folder.

    ``route_study()`` claims a study with a lock named ``<studies>/<study>/<study>.lock``, while
    the series-level path (``push_series_studylevel``) and ``is_study_locked()`` use
    ``<studies>/<study>/.lock`` - and ``check_force_study_timeout()`` uses ``.lock`` too. So the
    study-routing claim is invisible to everyone else: a second router happily buffers a newly
    received series into a study that is being emptied, and ``remove_study_folder()``'s
    ``shutil.rmtree()`` at the end of ``route_study`` deletes it.

    Required contract: while a study is being routed, other components must observe the study as
    locked, so a late series is buffered for the next routing pass instead of being deleted.
    """
    config = mercure_config(study_rules)
    study_uid = str(uuid.uuid4())
    study = f"{study_uid}#study_route"
    study_folder = buffer_series_in_study(config, str(uuid.uuid4()), study_uid, "series A", "task-a")

    late_series = str(uuid.uuid4())
    late_stem = f"{late_series}#slice"

    route_studies_real_move = route_studies.move_study_folder

    def move_then_receive(task_id, study_name, destination):
        """Real move of the buffered files, then a second router delivers another series."""
        real_result = route_studies_real_move(task_id, study_name, destination)
        # Another router process: same study, new series, arriving mid-flight.
        stem, tags = receive_series(config, late_series, study_uid, "series late")
        route_series.push_series_studylevel("task-late", {"study_route": True}, [stem], late_series, tags)
        return real_result

    mocked.patch.object(route_studies, "move_study_folder", side_effect=move_then_receive)

    assert route_studies.route_study(study) is True

    # The late series must still exist somewhere (still buffered, or routed in a later pass).
    survivors = files_named("/var", f"{late_stem}.dcm")
    assert survivors, (
        f"the series that arrived during study routing was deleted: {study_folder} was removed "
        f"while it was being written into"
    )


def test_study_routing_claim_is_visible_to_the_series_level_lock(
    fs: FakeFilesystem, mercure_config, mocked
) -> None:
    """While ``route_study`` holds a study, ``is_study_locked`` must report it as locked.

    Same root cause as the previous test, stated as the narrow invariant: the marker
    ``route_study`` writes must be the marker everybody else checks.
    """
    config = mercure_config(study_rules)
    study_uid = str(uuid.uuid4())
    study = f"{study_uid}#study_route"
    study_folder = buffer_series_in_study(config, str(uuid.uuid4()), study_uid, "series A", "task-a")

    # Precondition: an unclaimed study is not locked.
    assert route_studies.is_study_locked(str(study_folder)) is False

    observed = {}
    real_move = route_studies.move_study_folder

    def spy_move(task_id, study_name, destination):
        observed["locked"] = route_studies.is_study_locked(str(study_folder))
        return real_move(task_id, study_name, destination)

    mocked.patch.object(route_studies, "move_study_folder", side_effect=spy_move)

    assert route_studies.route_study(study) is True

    # While route_study() is working on the study, other router instances must see it claimed -
    # otherwise they keep adding series that the trailing rmtree() then destroys.
    assert observed.get("locked") is True, (
        "route_study() claims a study with a lock name that is_study_locked() (and "
        "push_series_studylevel()) never look at, so the claim is not exclusive"
    )


def test_study_task_file_is_not_rewritten_without_holding_the_study_lock(
    fs: FakeFilesystem, mercure_config, mocked
) -> None:
    """The force-complete rewrite in ``is_study_complete`` must happen under the study lock.

    ``route_studies()`` evaluates completeness (and, when a ``.force-complete`` marker from the
    web UI is present, *rewrites* ``task.json``) before any lock is taken - the claim only
    happens inside ``route_study``. Meanwhile series-level routers update the very same file with
    a read-modify-write under ``.lock`` (``update_study_task``). Two writers, no common lock: the
    later write silently reverts the earlier one, so either the operator's force-complete or a
    recorded series is lost.

    Required contract: every write to a study task file happens while the writer holds the lock
    the other writers take.
    """
    config = mercure_config(study_rules)
    study_uid = str(uuid.uuid4())
    study_folder = buffer_series_in_study(config, str(uuid.uuid4()), study_uid, "series A", "task-a")

    # The web UI's "force completion" marker.
    (study_folder / mercure_names.FORCE_COMPLETE).touch()

    writes: List[Tuple[str, bool]] = []
    real_write = route_studies.write_json_atomic

    def spy_write(path, payload, **kwargs):
        writes.append((str(path), route_studies.is_study_locked(str(study_folder))))
        return real_write(path, payload, **kwargs)

    mocked.patch.object(route_studies, "write_json_atomic", side_effect=spy_write)

    route_studies.route_studies({})

    assert writes, "precondition: the force-complete marker must update the study task file"
    unlocked = [path for path, locked in writes if not locked]
    assert not unlocked, f"study task file written without the study lock: {unlocked}"


def test_cleaner_does_not_delete_a_folder_another_service_has_locked(
    fs: FakeFilesystem, mercure_config, mocked
) -> None:
    """The cleaner must respect ``.lock``, which is what the writers use to protect a folder.

    ``push_series_complete()`` creates a lock in the destination folder "to prevent the cleaner
    module to work on the folder", and ``move_study_folder()`` does the same "to prevent any other
    module to work on the folder". ``clean_dir()`` never looks at the marker: it deletes every
    folder whose mtime exceeds the retention - and the emergency path calls it with a retention of
    zero, i.e. "delete everything", including the folder another service is writing into right
    now. The writer then fails mid-copy (or, worse, finishes into a folder that is gone) and the
    data is lost while it was still inside its retention period.

    Required contract: a locked folder is never a cleaning candidate.
    """
    config = mercure_config({"retention": 3600})

    success = Path(config.success_folder)
    locked = success / "being_written"
    locked.mkdir()
    # A router instance is halfway through filling this folder (see push_series_complete). Write the
    # marker directly: a FileLock object would be garbage collected here and its destructor would
    # remove the lock again.
    (locked / mercure_names.LOCK).touch()

    aged = success / "expired"
    aged.mkdir()
    (aged / "series#slice.dcm").write_bytes(b"data")

    # Both folders are older than the retention period.
    timestamp = os.path.getmtime(str(locked)) - 7200
    os.utime(str(locked), (timestamp, timestamp))
    os.utime(str(aged), (timestamp, timestamp))

    cleaner.clean_dir(str(success), timedelta(seconds=3600))

    assert not aged.exists(), "precondition: an expired, unlocked folder is cleaned up"
    assert locked.is_dir(), (
        "the cleaner deleted a folder that another service had locked; that folder is being "
        "written right now (and the emergency path deletes locked folders of any age)"
    )
