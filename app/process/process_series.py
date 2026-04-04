"""
process_series.py
=================
Helper functions for mercure's processor module.
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, cast

import common.config as config
import common.helper as helper
import common.log_helpers as log_helpers
import common.monitor as monitor
import common.notification as notification
from common.constants import mercure_events, mercure_names
from common.event_types import FailStage
from common.types import Task, TaskProcessing
from dispatch.send import update_fail_stage
from process.runtime_base import ContainerRuntime, get_runtime

logger = config.get_logger()


@log_helpers.clear_task_decorator_async
async def process_series(folder: Path) -> None:
    logger.info("----------------------------------------------------------------------------------")
    logger.info(f"Now processing {folder}")
    processing_success = False
    needs_dispatching = False

    lock_file = folder / mercure_names.PROCESSING
    lock = None
    task: Optional[Task] = None
    taskfile_path = folder / mercure_names.TASKFILE
    outputs: List = []
    runtime: Optional[ContainerRuntime] = None

    try:
        try:
            lock_file.touch(exist_ok=False)
        except FileExistsError:
            # Another instance already locked this folder.
            return
        except Exception as e:
            logger.error(f"Unable to create lock file {lock_file}")
            monitor.send_event(
                monitor.m_events.PROCESSING,
                monitor.severity.ERROR,
                f"Unable to create lock file in processing folder {lock_file}",
            )
            raise e

        if not taskfile_path.exists():
            logger.error(f"Task file {taskfile_path} does not exist")
            raise Exception(f"Task file {taskfile_path} does not exist")

        with open(taskfile_path, "r") as f:
            task = Task(**json.load(f))
        logger.setTask(task.id)
        if task.dispatch:
            needs_dispatching = True

        file_count_begin = len(list(folder.glob(mercure_names.DCMFILTER)))

        (folder / "in").mkdir()
        for child in folder.iterdir():
            if child.is_file() and child.name != ".processing":
                child.rename(folder / "in" / child.name)
        (folder / "out").mkdir()

        runtime = get_runtime()

        # Async runtimes (Nomad) send their own PROCESS_BEGIN event inside run().
        # Synchronous runtimes need it here because they may loop over multiple steps.
        if runtime.supports_multi_step:
            await monitor.async_send_task_event(
                monitor.task_event.PROCESS_BEGIN,
                task.id,
                file_count_begin,
                (task.process[0].module_name if isinstance(task.process, list)
                 else task.process.module_name)
                if task.process else "UNKNOWN",
                "Processing job running",
            )

        if runtime.supports_multi_step and isinstance(task.process, list):
            # --- Multi-step processing ---
            if task.process[0].retain_input_images:
                shutil.copytree(folder / "in", folder / "input_files")
            logger.info("==== TASK ====", task.dict())
            copied_task = task.copy(deep=True)
            try:
                for i, task_processing in enumerate(task.process):
                    copied_task.process = task_processing
                    with open(folder / "in" / mercure_names.TASKFILE, "w") as task_file:
                        json.dump(copied_task.dict(), task_file)

                    processing_success = await runtime.run(
                        task, folder, file_count_begin, task_processing
                    )
                    if not processing_success:
                        break

                    output = handle_processor_output(task, task_processing, i, folder)
                    outputs.append((task_processing.module_name, output))
                    (folder / "out" / "result.json").unlink(missing_ok=True)
                    shutil.rmtree(folder / "in")
                    if i < len(task.process) - 1:
                        (folder / "out").rename(folder / "in")
                        (folder / "out").mkdir()
                    task_processing.output = output

                if task.process[0].retain_input_images:
                    (folder / "input_files").rename(folder / "in")
                if outputs:
                    with open(folder / "out" / "result.json", "w") as fp:
                        json.dump(outputs, fp, indent=4)

            finally:
                with open(folder / "out" / mercure_names.TASKFILE, "w") as task_file:
                    json.dump(task.dict(), task_file, indent=4)

        elif isinstance(task.process, list):
            raise Exception(
                "Multiple processing steps are only supported on Docker and Podman runtimes."
            )
        else:
            # --- Single-step processing ---
            task_process = cast(TaskProcessing, task.process)
            processing_success = await runtime.run(
                task, folder, file_count_begin, task_process
            )
            if processing_success:
                output = handle_processor_output(task, task_process, 0, folder)
                task.process.output = output  # type: ignore
                with open(folder / "out" / mercure_names.TASKFILE, "w") as fp:
                    json.dump(task.dict(), fp, indent=4)
                outputs.append((task_process.module_name, output))

    except Exception:
        processing_success = False
        task_id = None
        if task is not None:
            task_id = task.id
        else:
            try:
                task_id = json.load(open(taskfile_path, "r"))["id"]
            except Exception:
                pass
        logger.error("Processing error.", task_id)  # handle_error

    finally:
        task_id = task.id if task is not None else "Unknown"

        # Synchronous runtimes (Docker, Podman): process_series owns result handling.
        # Async runtimes (Nomad): the runtime handles its own lifecycle.
        if runtime is None or not runtime.is_async:
            logger.info("Processing complete")
            push_input_task(folder / "in", folder / "out")
            if (
                task is not None
                and task.process
                and (
                    task.process[0] if isinstance(task.process, list) else task.process
                ).retain_input_images is True
            ):
                push_input_images(task_id, folder / "in", folder / "out")
            file_count_complete = len(
                list((folder / "out").glob(mercure_names.DCMFILTER))
            )
            move_results(task_id, folder, lock, processing_success, needs_dispatching)
            shutil.rmtree(folder, ignore_errors=True)

            if processing_success:
                monitor.send_task_event(
                    monitor.task_event.PROCESS_COMPLETE,
                    task_id,
                    file_count_complete,
                    "",
                    "Processing job complete",
                )
                if not needs_dispatching:
                    monitor.send_task_event(
                        monitor.task_event.COMPLETE, task_id, 0, "", "Task complete"
                    )
                    request_do_send = False
                    if (
                        outputs
                        and task
                        and (
                            applied_rule := config.mercure.rules.get(
                                task.info.get("applied_rule")
                            )
                        )
                        and applied_rule.notification_trigger_completion_on_request
                    ):
                        if notification.get_task_requested_notification(task):
                            request_do_send = True
                    trigger_notification(
                        task,  # type: ignore
                        mercure_events.COMPLETED,
                        notification.get_task_custom_notification(task),
                        request_do_send,
                    )
            else:
                monitor.send_task_event(
                    monitor.task_event.ERROR, task_id, 0, "", "Processing failed"
                )
                if task is not None:
                    trigger_notification(task, mercure_events.ERROR)
        else:
            # Async runtime (Nomad)
            if processing_success:
                logger.info("Done submitting for processing")
            else:
                logger.info("Unable to process task")
                move_results(task_id, folder, lock, False, False)
                monitor.send_task_event(
                    monitor.task_event.ERROR, task_id, 0, "", "Unable to process task"
                )
                if task is not None:
                    trigger_notification(task, mercure_events.ERROR)


def push_input_task(input_folder: Path, output_folder: Path) -> None:
    task_json = output_folder / "task.json"
    if not task_json.exists():
        try:
            shutil.copyfile(input_folder / "task.json", output_folder / "task.json")
        except Exception:
            try:
                task_id = json.load(open(input_folder / "task.json", "r"))["id"]
                logger.error(
                    f"Error copying task file to outfolder {output_folder}", task_id
                )  # handle_error
            except Exception:
                logger.error(
                    f"Error copying task file to outfolder {output_folder}", None
                )  # handle_error


def push_input_images(task_id: str, input_folder: Path, output_folder: Path) -> None:
    error_while_copying = False
    error_info = None
    for entry in os.scandir(input_folder):
        if entry.name.endswith(mercure_names.DCM):
            try:
                shutil.copyfile(input_folder / entry.name, output_folder / entry.name)
            except Exception:
                logger.exception(f"Error copying file to outfolder {entry.name}")
                error_while_copying = True
                error_info = sys.exc_info()
    if error_while_copying:
        logger.error(
            f"Error while copying files to output folder {output_folder}",
            task_id,
            exc_info=error_info,
        )  # handle_error


def handle_processor_output(
    task: Task, task_processing: TaskProcessing, index: int, folder: Path
) -> Any:
    output_file = folder / "out" / "result.json"
    if not output_file.is_file():
        logger.info("No result.json")
        return
    try:
        output = json.loads(output_file.read_text())
    except json.JSONDecodeError:
        logger.info("Failed to parse result.json")
        return
    logger.info("Read result.json:")
    logger.info(output)
    monitor.send_processor_output(task, task_processing, index, output)
    return output


def move_results(
    task_id: str,
    folder: Path,
    lock: Optional[helper.FileLock],
    processing_success: bool,
    needs_dispatching: bool,
) -> None:
    logger.debug(
        f"Moving results folder {folder} "
        f"{'with' if needs_dispatching else 'without'} dispatching"
    )
    lock_file = folder / mercure_names.LOCK
    if lock_file.exists():
        logger.error(
            f"Folder already contains lockfile {folder}/" + mercure_names.LOCK
        )
        return
    try:
        lock_file.touch(exist_ok=False)
    except Exception:
        logger.error(f"Error locking folder to be moved {folder}", task_id)  # handle_error
        return

    if lock is not None:
        lock.free()
    if not processing_success:
        logger.debug(f"Failing: {folder}")
        move_out_folder(
            task_id,
            folder,
            Path(config.mercure.error_folder),
            move_all=True,
            fail_stage=FailStage.PROCESSING,
        )
    else:
        if needs_dispatching:
            logger.debug(f"Dispatching: {folder}")
            move_out_folder(task_id, folder, Path(config.mercure.outgoing_folder))
        else:
            logger.debug(f"Success: {folder}")
            move_out_folder(task_id, folder, Path(config.mercure.success_folder))


def move_out_folder(
    task_id: str,
    source_folder: Path,
    destination_folder: Path,
    move_all: bool = False,
    fail_stage: Optional[FailStage] = None,
) -> None:
    target_folder = destination_folder / source_folder.name
    if target_folder.exists():
        new_name = source_folder.name.split("_")[0] + "_" + datetime.now().isoformat()
        target_folder = destination_folder / new_name

    logger.debug(
        f"Moving {source_folder} to {target_folder}, move_all: {move_all}"
    )
    logger.debug("--- source contents ---")
    for k in source_folder.glob("**/*"):
        logger.debug("{:>25}".format(str(k.relative_to(source_folder))))
    logger.debug("--------------")
    try:
        if move_all:
            shutil.move(str(source_folder), target_folder)
            if fail_stage and not update_fail_stage(target_folder, FailStage.PROCESSING):
                logger.error(f"Error updating fail stage for task {task_id}")
        else:
            shutil.move(str(source_folder / "out"), target_folder)
            lockfile = source_folder / mercure_names.LOCK
            lockfile.unlink()
    except Exception:
        logger.error(
            f"Error moving folder {source_folder} to {destination_folder}", task_id
        )  # handle_error


def trigger_notification(
    task: Task, event: mercure_events, details: str = "", send_always: bool = False
) -> None:
    current_rule_name = task.info.get("applied_rule")
    logger.debug(f"Notification {event.name}")
    if not current_rule_name:
        logger.error(
            f"Missing applied_rule in task file in task {task.id}", task.id
        )  # handle_error
        return
    notification.trigger_notification_for_rule(
        current_rule_name,
        task.id,
        event,
        task=task,
        details=details,
        send_always=send_always,
    )
