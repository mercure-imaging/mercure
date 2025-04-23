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
from typing import Dict, Optional

import common.config as config
# App-specific includes
import common.helper as helper
import common.influxdb
import common.monitor as monitor
import common.notification as notification
import graphyte
import hupper
from common.constants import mercure_defs, mercure_events, mercure_names
from common.types import Task, TaskProcessing
from process.process_series import (handle_processor_output, move_results, process_series, push_input_images, push_input_task,
                                    trigger_notification)
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


def backup_input_images(task_folder: Path) -> None:
    """
    Creates a backup of input DICOM files in an 'as_received' subfolder within the task folder.

    Args:
        task_folder: Path to the task folder
    """
    input_folder = task_folder
    backup_folder = task_folder / "as_received"
    backup_folder.mkdir(exist_ok=True)

    # Copy all DICOM files from input folder to backup folder
    for file in input_folder.glob('*'):
        if file.is_file():
            shutil.copy2(file, backup_folder)

    logger.info(f"Backed up input files for task folder {task_folder.name} to {backup_folder}")


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
        p_folder = c["path"]
        in_folder = p_folder / "in"
        out_folder = p_folder / "out"

        logger.debug(f"Complete task: {p_folder.name}")

        job_info = json.loads((p_folder / "nomad_job.json").read_text())

        # Move task.json over to the output directory if it wasn't moved by the processing module
        push_input_task(in_folder, out_folder)

        # Patch the nomad info into the task file.
        task_path = out_folder / mercure_names.TASKFILE
        task = Task(**json.loads(task_path.read_text()))

        with task_path.open("w") as f:
            task.nomad_info = job_info
            json.dump(task.dict(), f)

        # Copy input images if configured in rule
        task_processing = (task.process[0] if isinstance(task.process, list) else task.process)
        if not task_processing:
            continue
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
            continue

        needs_dispatching = True if task.get("dispatch") else False
        move_results(task.id, p_folder, None, True, needs_dispatching)
        shutil.rmtree(in_folder)
        (p_folder / "nomad_job.json").unlink()
        (p_folder / ".processing").unlink()
        shutil.rmtree(p_folder / "as_received", ignore_errors=True)

        p_folder.rmdir()
        monitor.send_task_event(
            monitor.task_event.PROCESS_COMPLETE, task.id, file_count_complete, "", "Processing complete"
        )
        # If dispatching not needed, then trigger the completion notification (for Nomad)
        if not needs_dispatching:
            trigger_notification(task, mercure_events.COMPLETED)
            monitor.send_task_event(monitor.task_event.COMPLETE, task.id, 0, "", "Task complete")

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
        selected_task_folder = prioritize_tasks(sorted_tasks, counter)
        # Return if no task of valid priority is found
        if selected_task_folder is None:
            return False
    except Exception as e:
        logger.error("Error while prioritizing tasks- ignoring priority")
        logger.error(e)
        selected_task_folder = Path(sorted_tasks[0])

    task_folder = selected_task_folder

    try:
        # Backup input images before processing
        backup_input_images(task_folder)

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


def prioritize_tasks(sorted_tasks: list, counter: int) -> Optional[Path]:
    """Returns the prioritized task based on the priority in the task file."""
    is_offpeak = helper._is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time())
    normal_task, urgent_task = None, None
    for task in sorted_tasks:
        task_folder = Path(task)
        taskfile_path = task_folder / mercure_names.TASKFILE
        with open(taskfile_path, "r") as f:
            task_instance = Task(**json.load(f))
        applied_rule = config.mercure.rules.get(task_instance.info.get("applied_rule"))
        if applied_rule is None:
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
    finally:  # Finish all asyncio tasks that might be still pending
        remaining_tasks = helper.asyncio.all_tasks(helper.loop)  # type: ignore[attr-defined]
        if remaining_tasks:
            helper.loop.run_until_complete(helper.asyncio.gather(*remaining_tasks))
        logger.info("Going down now")
