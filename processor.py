"""
processor.py
============
mercure' processor that executes processing modules on DICOM series filtered for processing. 
"""
# Standard python includes
import time
import signal
import os
import sys
import graphyte
import logging
import daiquiri
from pathlib import Path

# App-specific includes
import common.helper as helper
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs

from process.status import is_ready_for_processing
from process.process_series import process_series


daiquiri.setup(
    level=logging.INFO,
    outputs=(daiquiri.output.Stream(formatter=daiquiri.formatter.ColorFormatter(fmt="%(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s")),),
)
logger = daiquiri.getLogger("processor")


processor_lockfile = Path("")
processor_is_locked = False


def search_folder(counter):
    global processor_lockfile
    global processor_is_locked

    helper.g_log("events.run", 1)

    tasks = {}

    for entry in os.scandir(config.mercure["processing_folder"]):
        if entry.is_dir() and is_ready_for_processing(entry.path):
            modification_time = entry.stat().st_mtime
            tasks[entry.path] = modification_time

    # Check if processing has been suspended via the UI
    if processor_lockfile.exists():
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
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, "Exception while processing series")
        return False


def run_processor(args):
    """Main processing function that is called every second."""
    if helper.is_terminated():
        return

    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to update configuration. Skipping processing.")
        monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.WARNING, "Unable to update configuration (possibly locked)")
        return

    call_counter = 0

    while search_folder(call_counter):
        call_counter += 1
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return


def exit_processor(args):
    """Callback function that is triggered when the process terminates. Stops the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


def terminate_process(signalNumber, frame):
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.h_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


if __name__ == "__main__":
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

    appliance_name = config.mercure["appliance_name"]

    logger.info(f"Appliance name = {appliance_name}")
    logger.info(f"Instance  name = {instance_name}")
    logger.info(f"Instance  PID  = {os.getpid()}")
    logger.info(sys.version)

    monitor.configure("processor", instance_name, config.mercure["bookkeeper"])
    monitor.send_event(monitor.h_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure["graphite_ip"]) > 0:
        logger.info(f'Sending events to graphite server: {config.mercure["graphite_ip"]}')
        graphite_prefix = "mercure." + appliance_name + ".processor." + instance_name
        graphyte.init(config.mercure["graphite_ip"], config.mercure["graphite_port"], prefix=graphite_prefix)

    logger.info(f'Processing folder: {config.mercure["processing_folder"]}')
    processor_lockfile = Path(config.mercure["processing_folder"] + "/HALT")

    # Start the timer that will periodically trigger the scan of the incoming folder
    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure["dispatcher_scan_interval"], run_processor, exit_processor, {})
    main_loop.start()

    helper.g_log("events.boot", 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    # Process will exit here once the asyncio loop has been stopped
    monitor.send_event(monitor.h_events.SHUTDOWN, monitor.severity.INFO)
    logger.info("Going down now")
