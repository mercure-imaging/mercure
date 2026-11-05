"""
processor.py
============
mercure' processor that executes processing modules on DICOM series filtered for processing.
"""

import asyncio
# Standard python includes
import base64
import json
import os
import shutil
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import common.config as config
# App-specific includes
import common.helper as helper
import common.influxdb
import common.monitor as monitor
import common.notification as notification
import graphyte
import hupper
from common.constants import mercure_defs, mercure_events, mercure_names
from common.folder_io import move_into_folder
from common.json_io import write_json_atomic
from common.types import Task, TaskProcessing
from process.process_series import (backup_input_images, handle_processor_output, move_results, process_series,
                                    push_input_images, push_input_task, trigger_notification)
from process.status import is_ready_for_processing

import nomad

# Create local logger instance
logger = config.get_logger()
processing_loop = None  # type: helper.AsyncTimer  # type: ignore


processor_lockfile = None
processor_is_locked = False

try:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)  # type: ignore
    logger.info("Connected to Nomad")
except Exception:
    nomad_connection = None


def claim_completed_task(p_folder: Path) -> Optional[Path]:
    """Atomically claim a finished Nomad job folder. Returns the claim marker, or None.

    Collecting a job's results is the most destructive sequence in the processor: it rewrites the
    task file, moves ``out/`` to the success/error folder, deletes ``in/``, removes the markers and
    finally removes the task folder itself. Several processor instances scan the same folder, so
    this must be an exclusive claim, exactly like the ``.processing`` marker that
    ``process_series()`` takes before touching a task's contents.
    """
    claim = p_folder / mercure_names.COMPLETING
    try:
        claim.touch(exist_ok=False)
        return claim
    except FileExistsError:
        # Owned by another processor instance.
        return None
    except FileNotFoundError:
        # The folder disappeared between the scan and the claim.
        return None
    except Exception:
        logger.exception(f"Unable to claim completed task {p_folder}")
        return None


def collect_nomad_results(p_folder: Path) -> None:
    """Collect the results of a finished Nomad job. The caller must hold the claim on ``p_folder``."""
    in_folder = p_folder / "in"
    out_folder = p_folder / "out"

    logger.debug(f"Complete task: {p_folder.name}")

    job_info = json.loads((p_folder / "nomad_job.json").read_text())

    # Move task.json over to the output directory if it wasn't moved by the processing module
    push_input_task(in_folder, out_folder)

    # Patch the nomad info into the task file.
    task_path = out_folder / mercure_names.TASKFILE
    task = Task(**json.loads(task_path.read_text()))

    task.nomad_info = job_info
    write_json_atomic(task_path, task.dict())

    # Copy input images if configured in rule
    task_processing = (task.process[0] if isinstance(task.process, list) else task.process)
    if not task_processing:
        return
    if task_processing.retain_input_images is True:
        push_input_images(task.id, in_folder, out_folder)

    # Remember the number of DCM files in the output folder (for logging purpose)
    file_count_complete = len(list(Path(out_folder).glob(mercure_names.DCMFILTER)))
    handle_processor_output(task, task_processing, 0, p_folder)

    # If the only file is task.json, the processing failed
    if [p.name for p in out_folder.rglob("*")] == [mercure_names.TASKFILE]:
        logger.error("Processing failed", task.id)
        move_results(task.id, p_folder, None, False, False)
        trigger_notification(task, mercure_events.ERROR)
        return

    needs_dispatching = True if task.get("dispatch") else False
    if not move_results(task.id, p_folder, None, True, needs_dispatching):
        # The results are still in the task folder. Deleting them here would turn a transient I/O
        # error into data loss, so keep the folder (and its markers) for recovery.
        logger.error(f"Results of task {task.id} could not be moved. Keeping {p_folder} "
                     "for recovery", task.id)  # handle_error
        return
    shutil.rmtree(in_folder)
    (p_folder / "nomad_job.json").unlink()
    (p_folder / ".processing").unlink()
    shutil.rmtree(p_folder / "as_received", ignore_errors=True)

    # Release the claim before removing the folder (the marker is inside it); the caller's cleanup
    # is a no-op in that case and still covers the error paths.
    (p_folder / mercure_names.COMPLETING).unlink(missing_ok=True)
    p_folder.rmdir()
    monitor.send_task_event(
        monitor.task_event.PROCESS_COMPLETE, task.id, file_count_complete, "", "Processing complete"
    )
    # If dispatching not needed, then trigger the completion notification (for Nomad)
    if not needs_dispatching:
        trigger_notification(task, mercure_events.COMPLETED)
        monitor.send_task_event(monitor.task_event.COMPLETE, task.id, 0, "", "Task complete")


async def search_folder(counter) -> bool:
    global processor_lockfile
    global processor_is_locked
    global nomad_connection
    helper.g_log("events.run", 1)

    tasks: Dict[str, float] = {}

    complete = []
    for entry in os.scandir(config.mercure.processing_folder):
        logger.debug(f"Scanning folder {entry.name}")
        if entry.is_dir():
            if is_ready_for_processing(entry.path):
                logger.debug(f"{entry.name} ready for processing")
                modification_time = entry.stat().st_mtime
                tasks[entry.path] = modification_time
                continue

            # Some tasks are actually currently processing
            if (Path(entry.path) / ".processing").exists() and (Path(entry.path) / "nomad_job.json").exists():
                logger.debug(f"{entry.name} currently processing")
                with open(Path(entry.path) / "nomad_job.json", "r") as f:
                    id = json.load(f).get("DispatchedJobID")
                logger.debug(f"Job id: {id}")
                job_info = nomad_connection.job.get_job(id)
                # job_allocations = nomad_connection.job.get_allocations(id)
                status = job_info.get("Status")
                if status == "dead":
                    logger.debug(f"{entry.name} is complete")

                    logs = []
                    try:
                        allocations = nomad_connection.job.get_allocations(id)
                        alloc = allocations[-1]["ID"]

                        logger.debug("========== logs ==========")
                        for s in ("stdout", "stderr"):
                            result = nomad_connection.client.stream_logs.stream(alloc, "process", s)
                            if len(result):
                                data = json.loads(result).get("Data")
                                result = base64.b64decode(data).decode(encoding="utf-8")
                                result = f"{s}:\n" + result
                                logs.append(result)
                                logger.info(result)
                    except Exception:
                        logger.exception("Failed to retrieve process logs.")

                    if not config.mercure.processing_logs.discard_logs:
                        task_path = Path(entry.path) / "in" / mercure_names.TASKFILE
                        task = Task(**json.loads(task_path.read_text()))
                        assert isinstance(task.process, TaskProcessing)
                        monitor.send_process_logs(task.id, task.process.module_name, "\n".join(logs))
                    complete.append(dict(path=Path(entry.path)))  # , info=job_info, allocations=job_allocations))
                else:
                    logger.debug(f"Status: {status}")

    # Move complete tasks
    for c in complete:
        claim = claim_completed_task(c["path"])
        if claim is None:
            # Another processor instance got to this job first (or removed the folder while this
            # scan was looking at it). Doing anything else would corrupt that processor's task.
            logger.debug(f"{c['path'].name} already claimed by another processor")
            continue
        try:
            collect_nomad_results(c["path"])
        except Exception:
            # One broken task must not take the processor service down.
            logger.exception(f"Error while collecting results for {c['path'].name}")
        finally:
            claim.unlink(missing_ok=True)

    # Check if processing has been suspended via the UI
    if processor_lockfile and processor_lockfile.exists():
        if not processor_is_locked:
            processor_is_locked = True
            logger.info("Processing halted")
        return False
    else:
        if processor_is_locked:
            processor_is_locked = False
            logger.info("Processing resumed")

    # Return if no tasks have been found
    if not len(tasks):
        # logger.debug("No tasks found")
        return False

    sorted_tasks = [item[0] for item in sorted(tasks.items(), key=lambda x: x[1])]
    # TODO: Add priority sorting. However, do not honor the priority flag for, e.g., every third run
    #       so that stagnation of cases is avoided

    # Only process one case at a time because the processing might take a while and
    # another instance might have processed the other entries already. So the folder
    # needs to be refreshed each time
    try:
        to_quarantine: List[Tuple[Path, str]] = []
        selected_task_folder = prioritize_tasks(sorted_tasks, counter, to_quarantine)
        for folder, reason in to_quarantine:
            quarantine_task(folder, reason)
        # Return if no task of valid priority is found
        if selected_task_folder is None:
            return False
    except FileNotFoundError:
        # Another processor may have claimed the task and moved task.json while this
        # processor was evaluating the stale directory snapshot. prioritize_tasks() skips
        # this per candidate; this handler covers a failure outside that loop. Retrying on
        # the next tick is cheap (dispatcher_scan_interval) and works off a fresh listing.
        return False
    except Exception as e:
        # Never fall back to an arbitrary folder from the stale snapshot: it may already be
        # claimed by another processor, which would corrupt that processor's task.
        logger.error("Error while prioritizing tasks")
        logger.error(e)
        return False

    task_folder = selected_task_folder

    try:
        await process_series(task_folder)
        # Return true, so that the parent function will trigger another search of the folder
        return True
    except Exception:
        for p in (task_folder / "out" / mercure_names.TASKFILE, task_folder / "in" / mercure_names.TASKFILE):
            try:
                task_id = json.load(open(p))["id"]
                logger.error("Exception while processing", task_id)  # handle_error
                break
            except Exception:
                pass
        else:
            logger.error("Exception while processing", None)  # handle_error

        return False


def prioritize_tasks(sorted_tasks: list, counter: int,
                     quarantine: Optional[List[Tuple[Path, str]]] = None) -> Optional[Path]:
    """Returns the prioritized task based on the priority in the task file.

    Candidates are evaluated independently: a task that vanished or cannot be read is
    skipped here instead of aborting the whole pass, so one bad task file cannot stall
    every other task waiting in the processing folder.

    Tasks that can never be processed (malformed task file, rule no longer configured) are
    appended to ``quarantine`` as ``(folder, reason)``; the caller moves them to the error
    folder. This function itself does not touch the file system.
    """
    is_offpeak = helper._is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time())
    normal_task, urgent_task = None, None
    for task in sorted_tasks:
        task_folder = Path(task)
        taskfile_path = task_folder / mercure_names.TASKFILE
        try:
            with open(taskfile_path, "r") as f:
                task_instance = Task(**json.load(f))
        except FileNotFoundError:
            # Another processor claimed this task and moved task.json mid-scan; skip it.
            continue
        except ValueError as e:
            # Malformed JSON or a task file that does not match the schema (pydantic's
            # ValidationError is a ValueError). Task files are written atomically into locked
            # folders, so this will not fix itself: quarantine it instead of skipping it forever.
            if quarantine is not None:
                quarantine.append((task_folder, f"Unreadable task file: {e}"))
            continue
        except Exception as e:
            # Unreadable for another reason (permissions, a failing mount): possibly transient,
            # so skip it for this pass and try again on the next one.
            logger.error(f"Unable to read task file {taskfile_path}", None)  # handle_error
            logger.error(e)
            continue
        rule_name = task_instance.info.get("applied_rule")
        applied_rule = config.mercure.rules.get(rule_name)
        if applied_rule is None:
            # The rule was renamed or deleted while the task was queued. The task stays invisible in
            # the processing folder unless it is moved where the operator looks for stuck work.
            if quarantine is not None:
                quarantine.append((task_folder, f"Rule '{rule_name}' is not configured"))
            continue
        priority = applied_rule.get('priority')
        if priority == "urgent" and urgent_task is None:
            urgent_task = task_folder
        elif (priority == "normal" or (priority == "offpeak" and is_offpeak)) and normal_task is None:
            normal_task = task_folder
        if (urgent_task is not None) and (normal_task is not None):
            break
    # Prioritize urgent task over normal task but reverse the order every third run
    if (counter % 3) < 2:
        return urgent_task or normal_task
    return normal_task or urgent_task


def _quarantine_reason(folder: Path) -> Optional[str]:
    """Re-check under the claim why ``folder`` cannot be processed. None if it now can be."""
    try:
        task = Task.from_file(folder / mercure_names.TASKFILE)
    except FileNotFoundError:
        return None
    except ValueError as e:
        return f"Unreadable task file: {e}"
    rule_name = task.info.get("applied_rule")
    if rule_name not in config.mercure.rules:
        return f"Rule '{rule_name}' is not configured"
    return None


def quarantine_task(folder: Path, reason: str) -> bool:
    """Move a task that can never be processed to the error folder. True if it was moved.

    The folder is claimed with ``.processing`` first, exactly like ``process_series()`` does, so
    that a task another processor instance is working on is never moved, and the reason is
    re-checked under the claim (the scan's view may be stale). The input files are backed up into
    ``as_received/`` beforehand, which is what the web UI's restart needs once the task file or the
    rule has been fixed.
    """
    claim = folder / mercure_names.PROCESSING
    try:
        claim.touch(exist_ok=False)
    except (FileExistsError, FileNotFoundError):
        return False  # claimed or removed by another processor in the meantime
    except Exception:
        logger.exception(f"Unable to claim {folder} for quarantine")
        return False

    moved = False
    try:
        current_reason = _quarantine_reason(folder)
        if current_reason is None:
            return False
        backup_input_images(folder)
        target = move_into_folder(folder, config.mercure.error_folder)
        moved = True
        (target / mercure_names.PROCESSING).unlink(missing_ok=True)
        message = f"Moved task {folder.name} to the error folder: {current_reason}"
        logger.error(message, None)  # handle_error (also reports the event to the bookkeeper)
        return True
    except Exception:
        logger.exception(f"Unable to move {folder} to the error folder")
        return moved
    finally:
        if not moved:
            claim.unlink(missing_ok=True)


async def run_processor() -> None:
    """Main processing function that is called every second."""
    if helper.is_terminated():
        return
    try:
        config.read_config()
    except Exception:
        logger.warning(  # handle_error
            "Unable to update configuration. Skipping processing",
            None,
            event_type=monitor.m_events.CONFIG_UPDATE,
        )
        return

    call_counter = 0

    while await search_folder(call_counter):
        call_counter += 1
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return


def exit_processor() -> None:
    """Callback function that is triggered when the process terminates. Stops the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


async def terminate_process(signalNumber, loop) -> None:
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: processing_loop can be read here because it has been declared as global variable
    if "processing_loop" in globals() and processing_loop.is_running:
        processing_loop.stop()
    helper.trigger_terminate()


def main(args=sys.argv[1:]) -> None:
    global processor_lockfile

    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        hupper.start_reloader("processor.main")
        import logging

        logging.getLogger("watchdog").setLevel(logging.WARNING)
    logger.info("")
    logger.info(f"mercure DICOM Processor ver {mercure_defs.VERSION}")
    logger.info("--------------------------------------------")
    logger.info("")

    # Register system signals to be caught
    signals = (signal.SIGTERM, signal.SIGINT)
    for s in signals:
        helper.loop.add_signal_handler(s, lambda s=s: asyncio.create_task(terminate_process(s, helper.loop)))

    instance_name = "main"

    if len(sys.argv) > 1:
        instance_name = sys.argv[1]

    # Read the configuration file and terminate if it cannot be read
    try:
        config.read_config()
    except Exception:
        logger.exception("Cannot start service. Going down.")
        sys.exit(1)

    appliance_name = config.mercure.appliance_name

    logger.info(f"Appliance name = {appliance_name}")
    logger.info(f"Instance  name = {instance_name}")
    logger.info(f"Instance  PID  = {os.getpid()}")
    logger.info(f"Thread ID  = {threading.get_native_id()}")
    logger.info(sys.version)

    notification.setup()
    monitor.configure("processor", instance_name, config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure.graphite_ip) > 0:
        logger.info(f"Sending events to graphite server: {config.mercure.graphite_ip}")
        graphite_prefix = "mercure." + appliance_name + ".processor." + instance_name
        graphyte.init(config.mercure.graphite_ip, config.mercure.graphite_port, prefix=graphite_prefix)

    if len(config.mercure.influxdb_host) > 0:
        logger.info(f"Sending events to influxdb server: {config.mercure.influxdb_host}")
        common.influxdb.init(
            config.mercure.influxdb_host,
            config.mercure.influxdb_token,
            config.mercure.influxdb_org,
            config.mercure.influxdb_bucket,
            "mercure." + appliance_name + ".processor." + instance_name
        )

    logger.info(f"Processing folder: {config.mercure.processing_folder}")
    processor_lockfile = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)

    # Start the timer that will periodically trigger the scan of the incoming folder
    global processing_loop
    processing_loop = helper.AsyncTimer(config.mercure.dispatcher_scan_interval, run_processor)  # , exit_processor)

    helper.g_log("events.boot", 1)

    try:
        processing_loop.run_until_complete(helper.loop)
        # # Process will exit here once the asyncio loop has been stopped
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    except Exception as e:
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.ERROR, str(e))
    finally:
        # Bounded shutdown; see helper.drain_pending_tasks().
        helper.drain_pending_tasks(helper.loop)
        logger.info("Going down now")
