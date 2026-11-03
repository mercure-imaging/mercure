"""
test_atomic_writes.py
=====================

Task files and the configuration file are currently written with ``open(path, "w")``
followed by ``json.dump``, which truncates the target *before* any new content exists.
A crash, a full disk or a killed service in that window leaves a truncated file behind,
and every later reader treats it as corrupt: the processor cannot read the task at all
(see ``prioritize_tasks``), and every service fails to read ``mercure.json``.

These tests pin the required contract: a reader must only ever observe the complete
previous file or the complete new one, and a failed write must not damage surrounding
state (the previous content, and the config lock file).
"""
import os
import uuid
from pathlib import Path

import pytest
from common import config
from common.constants import mercure_names
from common.types import Task, TaskInfo
from docker.models.containers import ContainerCollection
from docker.models.images import ImageCollection
from process import processor
from process.process_series import backup_input_images

from .test_processor import config_partial, create_and_route
from .testing_common import FakeDockerContainer, make_fake_processor


def make_task(task_id: str) -> Task:
    """Build a minimal but valid task for file-write tests."""
    return Task(
        id=task_id,
        info=TaskInfo(
            action="process",
            uid="TESTFAKEUID",
            uid_type="series",
            triggered_rules={"catchall": True},
            applied_rule="catchall",
            patient_name="Test",
            mrn="TESTMRN",
            acc="TESTACC",
            mercure_version="0.0.0",
            mercure_appliance="test",
            mercure_server="testhost",
        ),
    )


def crashy_json_dump(payload, fileobj, *args, **kwargs) -> None:
    """Stand in for json.dump: write some bytes, then die as a crash would.

    Replacing json.dump rather than open() reproduces the real hazard: the target has
    already been truncated by the time serialisation fails.
    """
    fileobj.write('{"id": "partially written')
    raise RuntimeError("simulated crash while serialising")


def test_task_file_write_failure_leaves_previous_file_intact(fs, mocked, mercure_config):
    """A task file write that dies mid-serialisation must not destroy the old file."""
    mercure_config({"process_runner": "docker", **config_partial})
    task = make_task("task-write-failure")
    taskfile = Path("/var/processing") / task.id / mercure_names.TASKFILE
    taskfile.parent.mkdir(parents=True)

    # Write a complete, valid task file the way production does.
    task.to_file(taskfile)
    previous_content = taskfile.read_text()
    assert previous_content != ""

    # Simulate a crash part-way through the rewrite.
    mocked.patch("json.dump", new=crashy_json_dump)
    with pytest.raises(RuntimeError):
        task.to_file(taskfile)

    # The reader's contract: the previous complete file survives, not a truncated one.
    assert taskfile.read_text() == previous_content
    # And the failed attempt must not leave scratch files behind in the task folder.
    assert sorted(p.name for p in taskfile.parent.iterdir()) == [mercure_names.TASKFILE]


def test_save_config_failure_leaves_previous_config_intact(fs, mocked, mercure_config):
    """A failed config save must not leave a truncated mercure.json for all services."""
    mercure_config({"process_runner": "docker", **config_partial})
    config_file = Path(config.configuration_filename)

    # Every service re-reads this file each tick, so its current bytes matter to all of them.
    previous_content = config_file.read_text()
    assert previous_content != ""

    mocked.patch("json.dump", new=crashy_json_dump)
    with pytest.raises(RuntimeError):
        config.save_config()

    # A torn config is an appliance-wide outage; the old one has to stay in place.
    assert config_file.read_text() == previous_content


def test_save_config_failure_does_not_leave_a_lock_file(fs, mocked, mercure_config):
    """Contract guard: a failed config save must not wedge the config writer.

    This passes today, but only as a side effect of ``helper.FileLock.__del__`` releasing
    the lock during garbage collection rather than from explicit cleanup in
    ``save_config``. The atomic rewrite must not lose that property, otherwise every later
    ``save_config()`` raises "Configuration file locked" until an operator deletes
    ``mercure.lock`` by hand.
    """
    mercure_config({"process_runner": "docker", **config_partial})
    config_file = Path(config.configuration_filename)
    lock_file = (config_file.parent / config_file.stem).with_suffix(mercure_names.LOCK)
    assert not lock_file.exists()

    mocked.patch("json.dump", new=crashy_json_dump)
    with pytest.raises(RuntimeError):
        config.save_config()

    # The failed save must not leave the configuration locked.
    assert not lock_file.exists()


def test_backup_input_images_ignores_incomplete_write_temp_files(fs, mercure_config):
    """Atomic writes may leave scratch files behind after a crash; backups must ignore them.

    ``backup_input_images`` currently copies every plain file it finds, so a leftover
    ``*.json.tmp`` ends up inside ``as_received`` and then in the operator's failure folder.
    """
    processing_folder = Path(mercure_config({"process_runner": "docker", **config_partial}).processing_folder)
    task_folder = processing_folder / "task-with-stray"
    task_folder.mkdir(parents=True)

    # The task's own contents.
    (task_folder / "test1.dcm").write_text("dicom content")
    (task_folder / mercure_names.TASKFILE).write_text('{"id": "task-with-stray"}')
    # A scratch file left by an interrupted atomic write (mkstemp name, hidden prefix).
    stray = task_folder / ".3f9a1cbe.json.tmp"
    stray.write_text('{"id": "partially written')

    backup_input_images(task_folder)

    backup_folder = task_folder / "as_received"
    # Real inputs are still backed up.
    assert (backup_folder / "test1.dcm").exists()
    assert (backup_folder / mercure_names.TASKFILE).exists()
    # An incomplete write artefact is not task input and must not be copied.
    assert not (backup_folder / stray.name).exists()
    assert [p.name for p in backup_folder.glob("*.json.tmp")] == []


@pytest.mark.asyncio
async def test_process_series_does_not_sweep_temp_files_into_the_container(
    fs, mercure_config, mocked
):
    """A stray scratch file must not be moved into ``in/`` and handed to a processing module.

    ``process_series`` moves every plain file except ``.processing`` into ``in/``, so a
    leftover ``*.json.tmp`` would be bind-mounted into the container and reappear in the
    results folder.
    """
    config = mercure_config({"process_runner": "docker", **config_partial})
    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    processor_folder = next(Path("/var/processing").iterdir())
    # Same artefact as above, present before the task is claimed and its inputs are moved.
    stray = processor_folder / ".7b2d0a11.json.tmp"
    stray.write_text('{"id": "partially written')

    # Standard fakes for the Docker runtime used by the rest of this suite.
    fake_run = mocked.Mock(return_value=FakeDockerContainer(),
                           side_effect=make_fake_processor(fs, mocked, False))

    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    mocked.patch.object(ImageCollection, "pull", new=lambda *args, **kwargs: None)

    await processor.run_processor()

    success_task_folder = Path("/var/success") / processor_folder.name
    assert success_task_folder.exists(), "task did not complete"
    # Nothing from the interrupted write may reach the task's output.
    assert [p.name for p in success_task_folder.rglob("*.json.tmp")] == []
    # The container's input folder is where the sweep would have put it; confirm by name too.
    assert not any(name.endswith(".json.tmp") for name in os.listdir(success_task_folder))


def test_new_task_file_is_readable_by_the_processing_user(fs, mocked, mercure_config):
    """Contract guard for an atomic rewrite: a fresh task file must be 0644, not 0600.

    This passes today (plain ``open(path, "w")`` honours the umask). It exists because the
    obvious atomic implementation uses ``tempfile.mkstemp``, which creates ``0600`` files;
    the helper must set the mode explicitly or a processing module could no longer read its
    task file.
    """
    mercure_config({"process_runner": "docker", **config_partial})
    task = make_task("task-mode-check")
    taskfile = Path("/var/processing") / task.id / mercure_names.TASKFILE
    taskfile.parent.mkdir(parents=True)

    task.to_file(taskfile)

    assert oct(taskfile.stat().st_mode & 0o777) == "0o644"


def test_task_file_rewrite_preserves_existing_mode(fs, mocked, mercure_config):
    """Contract guard for an atomic rewrite of a file whose mode was widened.

    ``docker_runtime`` chmods ``in/**`` to 0666 so a module running as a different uid can
    read its inputs; a rewrite that silently narrows the mode back to 0644 would break it.
    """
    mercure_config({"process_runner": "docker", **config_partial})
    task = make_task("task-mode-rewrite")
    taskfile = Path("/var/processing") / task.id / mercure_names.TASKFILE
    taskfile.parent.mkdir(parents=True)
    task.to_file(taskfile)
    os.chmod(taskfile, 0o666)

    task.to_file(taskfile)

    assert oct(taskfile.stat().st_mode & 0o777) == "0o666"
