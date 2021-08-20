"""
router.py
=========
mercure's central router module that evaluates the routing rules and decides which series should be sent to which target. 
"""

# Standard python includes
import time
import signal
import os
import sys
import graphyte
import logging
import daiquiri
from typing import Dict

# App-specific includes
from common.constants import mercure_config, mercure_defs, mercure_folders, mercure_names
import common.helper as helper
import common.config as config
import common.monitor as monitor
from routing.route_series import route_series, route_error_files
from routing.route_studies import route_studies

# Setup daiquiri logger
daiquiri.setup(
    level=logging.INFO,
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt="%(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s"
            )
        ),
    ),
)
# Create local logger instance
logger = daiquiri.getLogger("router")


def terminate_process(signalNumber, frame) -> None:
    """
    Triggers the shutdown of the service
    """
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def run_router(args=None) -> None:
    """
    Main processing function that is called every second
    """
    if helper.is_terminated():
        return

    helper.g_log("events.run", 1)

    # logger.info('')
    # logger.info('Processing incoming folder...')

    try:
        config.read_config()
    except Exception:
        error_message = "Unable to update configuration. Skipping processing."
        logger.exception(error_message)
        monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.WARNING, error_message)
        return

    filecount = 0
    series: Dict[str, float] = {}
    complete_series = {}

    error_files_found = False

    # Check the incoming folder for completed series. To this end, generate a map of all
    # series in the folder with the timestamp of the latest DICOM file as value
    for entry in os.scandir(config.mercure[mercure_folders.INCOMING]):
        if entry.name.endswith(mercure_names.TAGS) and not entry.is_dir():
            filecount += 1
            seriesString = entry.name.split(mercure_defs.SEPARATOR, 1)[0]
            modificationTime = entry.stat().st_mtime

            if seriesString in series.keys():
                if modificationTime > series[seriesString]:
                    series[seriesString] = modificationTime
            else:
                series[seriesString] = modificationTime
        # Check if at least one .error file exists. In that case, the incoming folder should
        # be searched for .error files at the end of the update run
        if (not error_files_found) and entry.name.endswith(mercure_names.ERROR):
            error_files_found = True

    # Check if any of the series exceeds the "series complete" threshold
    for series_entry in series:
        if (time.time() - series[series_entry]) > config.mercure["series_complete_trigger"]:
            complete_series[series_entry] = series[series_entry]

    # logger.info(f'Files found     = {filecount}')
    # logger.info(f'Series found    = {len(series)}')
    # logger.info(f'Complete series = {len(complete_series)}')
    helper.g_log("incoming.files", filecount)
    helper.g_log("incoming.series", len(series))

    # Process all complete series
    for complete_entry in sorted(complete_series):
        try:
            route_series(complete_entry)
        except Exception:
            error_message = f"Problems while processing series {complete_entry}"
            logger.exception(error_message)
            monitor.send_series_event(monitor.s_events.ERROR, complete_entry, 0, "", error_message)
            monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return

    if error_files_found:
        route_error_files()

    # Now, check if studies in the studies folder are ready for routing/processing
    route_studies()


def exit_router(args) -> None:
    """
    Callback function that is triggered when the process terminates. Stops the asyncio event loop
    """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


# Main entry point of the router module
if __name__ == "__main__":
    logger.info("")
    logger.info(f"mercure DICOM Router ver {mercure_defs.VERSION}")
    logger.info("-----------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT, terminate_process)
    signal.signal(signal.SIGTERM, terminate_process)

    instance_name = "main"

    # Read the optional instance name from the argument (if running multiple instances in one appliance)
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

    monitor.configure("router", instance_name, config.mercure["bookkeeper"])
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure["graphite_ip"]) > 0:
        logger.info(f'Sending events to graphite server: {config.mercure["graphite_ip"]}')
        graphite_prefix = "mercure." + appliance_name + ".router." + instance_name
        graphyte.init(config.mercure["graphite_ip"], config.mercure["graphite_port"], prefix=graphite_prefix)

    logger.info(f"Incoming   folder: {config.mercure[mercure_folders.INCOMING]}")
    logger.info(f"Studies    folder: {config.mercure[mercure_folders.STUDIES]}")
    logger.info(f"Outgoing   folder: {config.mercure[mercure_folders.OUTGOING]}")
    logger.info(f"Processing folder: {config.mercure[mercure_folders.PROCESSING]}")

    # Start the timer that will periodically trigger the scan of the incoming folder
    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure["router_scan_interval"], run_router, exit_router, {})
    main_loop.start()

    helper.g_log("events.boot", 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    # Process will exit here once the asyncio loop has been stopped
    monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    logger.info("Going down now")
