"""
processor.py
============
mercure' processor that executes processing modules on DICOM series filtered for processing. 
"""

# Standard python includes
import shutil
import signal
import os
import sys
import json
import graphyte
import daiquiri
import nomad
from pathlib import Path
import hupper

# App-specific includes
from common.types import TaskInfo
import common.helper as helper
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs, mercure_names, mercure_events
from process.status import is_ready_for_processing
from process.process_series import process_series, move_results, trigger_notification


# Setup daiquiri logger
daiquiri.setup(
    config.get_loglevel(),
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt="%(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s"
            )
        ),
    ),
)
# Create local logger instance
logger = daiquiri.getLogger("processor")
main_loop = None  # type: helper.RepeatedTimer # type: ignore


processor_lockfile = None
processor_is_locked = False

try:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)
    logger.info("Connected to Nomad")
except:
    nomad_connection = None


def search_folder(counter) -> bool:
    global processor_lockfile
    global processor_is_locked
    global nomad_connection
    helper.g_log("events.run", 1)

    tasks = {}

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
                    # logger.debug(job_allocations)
                    complete.append(dict(path=Path(entry.path)))  # , info=job_info, allocations=job_allocations))
                else:
                    logger.debug(f"Status: {status}")

    # Move complete tasks
    for c in complete:
        p_folder = c["path"]
        in_folder = p_folder / "in"
        out_folder = p_folder / "out"

        logger.debug(f"Complete task: {p_folder.name}")

        with open(p_folder / "nomad_job.json", "r") as f:
            job_info = json.load(f)

        # Move task.json over to the output directory if it wasn't moved by the processing module
        task_json = out_folder / "task.json"
        if not task_json.exists():
            shutil.copyfile(in_folder / "task.json", out_folder / "task.json")

        # Patch the nomad info into the task file.
        with task_json.open("r") as f:
            task = json.load(f)
        with task_json.open("w") as f:
            task = {**task, "nomad_info": job_info}
            json.dump(task, f)

        # If the only file is task.json, the processing failed
        if [p.name for p in out_folder.rglob("*")] == ["task.json"]:
            logger.error("Processing failed.")
            move_results(str(p_folder), None, False, False)
            trigger_notification(task.get("info"), mercure_events.ERROR)
            continue

        needs_dispatching = True if task.get("dispatch") else False
        move_results(str(p_folder), None, True, needs_dispatching)
        shutil.rmtree(in_folder)
        (p_folder / "nomad_job.json").unlink()
        (p_folder / ".processing").unlink()
        p_folder.rmdir()
        # If dispatching not needed, then trigger the completion notification (for Nomad)
        if not needs_dispatching:
            trigger_notification(task.get("info"), mercure_events.COMPLETION)

    # Check if processing has been suspended via the UI
    if processor_lockfile and processor_lockfile.exists():
        if not processor_is_locked:
            processor_is_locked = True
            logger.info(f"Processing halted")
        return False
    else:
        if processor_is_locked:
            processor_is_locked = False
            logger.info("Processing resumed")

    # Return if no tasks have been found
    if not len(tasks):
        return False

    sorted_tasks = sorted(tasks)
    # TODO: Add priority sorting. However, do not honor the priority flag for every third run
    #       so that stagnation of cases is avoided

    # Only process one case at a time because the processing might take a while and
    # another instance might have processed the other entries already. So the folder
    # needs to be refreshed each time
    task = sorted_tasks[0]

    try:
        process_series(task)
        # Return true, so that the parent function will trigger another search of the folder
        return True
    except Exception:
        logger.exception(f"Problems while processing series {task}")
        monitor.send_series_event(monitor.s_events.ERROR, entry, 0, "", "Exception while processing")
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, "Exception while processing series")
        return False


def run_processor(args=None) -> None:
    """Main processing function that is called every second."""
    if helper.is_terminated():
        return
    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to update configuration. Skipping processing.")
        monitor.send_event(
            monitor.m_events.CONFIG_UPDATE, monitor.severity.WARNING, "Unable to update configuration (possibly locked)"
        )
        return

    call_counter = 0

    while search_folder(call_counter):
        call_counter += 1
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return


def exit_processor(args) -> None:
    """Callback function that is triggered when the process terminates. Stops the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


def terminate_process(signalNumber, frame) -> None:
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def main(args=sys.argv[1:]) -> None:
    global processor_lockfile

    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        reloader = hupper.start_reloader("processor.main")

    logger.info("")
    logger.info(f"mercure DICOM Processor ver {mercure_defs.VERSION}")
    logger.info("--------------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT, terminate_process)
    signal.signal(signal.SIGTERM, terminate_process)

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
    logger.info(sys.version)

    monitor.configure("processor", instance_name, config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure.graphite_ip) > 0:
        logger.info(f"Sending events to graphite server: {config.mercure.graphite_ip}")
        graphite_prefix = "mercure." + appliance_name + ".processor." + instance_name
        graphyte.init(config.mercure.graphite_ip, config.mercure.graphite_port, prefix=graphite_prefix)

    logger.info(f"Processing folder: {config.mercure.processing_folder}")
    processor_lockfile = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)

    # Start the timer that will periodically trigger the scan of the incoming folder
    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure.dispatcher_scan_interval, run_processor, exit_processor, {})
    main_loop.start()

    helper.g_log("events.boot", 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    # Process will exit here once the asyncio loop has been stopped
    monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    logger.info("Going down now")


if __name__ == "__main__":
    main()
