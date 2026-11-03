"""
test_processor_race.py
======================

Two more races between the multiple ``processor`` instances mercure runs (``processor`` x2 in the
integration harness and in the systemd/docker deployments).

The claim that makes a task folder owned by exactly one processor is the ``.processing`` marker,
created atomically in :func:`process.process_series.process_series` (see commit ``7694a80``). The
Nomad completion path inside ``processor.search_folder`` - the code that collects the results of a
job that a Nomad allocation finished - never takes that claim, even though it is the most
destructive code in the file: it rewrites the task file, moves ``out/`` to the success/error
folder, deletes ``in/``, removes the markers and finally removes the task folder itself. Two
processors that scan the same folder in the same tick therefore both "finish" the same task.
"""
import asyncio
import json
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict

import pytest
from common.constants import mercure_names
from common.types import Config, Module, Rule, Task, TaskInfo, TaskProcessing
from process import processor
from pytest_mock import MockerFixture

config_partial: Dict = {
    "modules": {
        "test_module": Module(docker_tag="busybox:stable", settings={"fizz": "buzz"}).dict(),
    },
    "rules": {
        "catchall": Rule(
            rule="True",
            action="process",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    },
}


def make_finished_nomad_task() -> Path:
    """Create a processing folder that holds a Nomad job which has just finished successfully."""
    task_folder = Path("/var/processing") / f"nomad-task-{uuid.uuid4()}"
    (task_folder / "in").mkdir(parents=True)
    (task_folder / "out").mkdir()

    task = Task(
        id=task_folder.name,
        info=TaskInfo(
            action="process",
            uid="TESTFAKEUID",
            uid_type="series",
            triggered_rules={"catchall": True},
            applied_rule="catchall",
            mrn="TESTMRN",
            acc="TESTACC",
            mercure_version="0.0.0",
            mercure_appliance="test",
            mercure_server="testhost",
        ),
        process=TaskProcessing(
            module_name="test_module",
            module_config=config_partial["modules"]["test_module"],
            settings={"fizz": "buzz"},
            retain_input_images=False,
        ),
    )
    task.to_file(task_folder / "in" / mercure_names.TASKFILE)
    (task_folder / "in" / "input.dcm").write_bytes(b"\x00\x00DICMfake")

    # The module delivered its result, so the task is a success candidate.
    task.to_file(task_folder / "out" / mercure_names.TASKFILE)
    (task_folder / "out" / "result.dcm").write_bytes(b"\x00\x00DICMfake")

    # Markers that identify the folder as "dispatched to Nomad and still running".
    (task_folder / mercure_names.PROCESSING).touch()
    (task_folder / "nomad_job.json").write_text(json.dumps({"DispatchedJobID": "job-1"}))
    return task_folder


@pytest.mark.asyncio
async def test_two_processors_completing_one_nomad_job_move_the_results_only_once(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """Exactly one processor may finish a finished Nomad task.

    ``search_folder`` recognises a completed Nomad job (``.processing`` + ``nomad_job.json`` +
    job status ``dead``) and immediately collects its results - without the ``.processing`` claim
    that :func:`process_series` uses to make task ownership exclusive. Both processors see the same
    finished job in the same tick, so both run the completion sequence.

    The failure modes are user visible: the task is completed/dispatched/notifications fired twice,
    and the losing processor races the winner's ``rmtree`` and dies with ``FileNotFoundError``
    (which ``run_processor`` does not catch, so the processor service goes down).

    Required contract: the completion pass must claim the task folder the same way the processing
    pass does, and a processor that fails to claim it must do nothing at all.
    """
    mercure_config({"process_runner": "nomad", "processing_logs": {"discard_logs": True}, **config_partial})
    task_folder = make_finished_nomad_task()

    # A Nomad allocation that reports the job as finished.
    nomad = mocked.Mock()
    nomad.job.get_job.return_value = {"Status": "dead"}
    nomad.job.get_allocations.return_value = []
    mocked.patch.object(processor, "nomad_connection", nomad)

    # ``move_results`` is the point of no return: it moves out/ to the success or error folder and
    # hands the task to the dispatcher (or marks it complete). Spy, do not replace, so that the
    # filesystem evolves exactly as it does in production.
    move_spy = mocked.spy(processor, "move_results")

    # Hold the first processor inside the completion pass, right before it moves the results, so
    # that the second processor observes the very same "job is dead, nobody claimed it" state.
    inside_completion = threading.Event()
    release_first = threading.Event()
    output_calls = []

    real_output = processor.handle_processor_output

    def barrier_output(*args, **kwargs):
        output_calls.append(args[3] if len(args) > 3 else kwargs.get("folder"))
        if len(output_calls) == 1:
            inside_completion.set()
            assert release_first.wait(timeout=5), "timed out waiting for the second processor"
        return real_output(*args, **kwargs)

    mocked.patch.object(processor, "handle_processor_output", side_effect=barrier_output)

    errors = []

    def run_one_scan():
        try:
            return asyncio.run(processor.search_folder(0))
        except BaseException as exc:  # noqa: BLE001 - the scan must not raise at all
            errors.append(exc)
            return None

    first = asyncio.create_task(asyncio.to_thread(run_one_scan))
    assert await asyncio.to_thread(inside_completion.wait, 5), "first processor never reached the completion pass"
    try:
        # Second processor, same tick, same folder, still no claim on it.
        second = await asyncio.wait_for(asyncio.to_thread(run_one_scan), timeout=10)
        assert second is False, f"the second scan blew up: {errors!r}"
    finally:
        release_first.set()
    await asyncio.wait_for(first, timeout=10)

    assert move_spy.call_count == 1, (
        f"both processors ran the completion pass for the same Nomad task "
        f"({move_spy.call_count} result moves): the completion pass in search_folder() takes no claim"
    )
    assert not errors, f"a processor died while finishing a task it did not own: {errors!r}"
