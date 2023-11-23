"""
router.py
=========
mercure's central router module that evaluates the routing rules and decides which series should be sent to which target. 
"""

# Standard python includes
import asyncio
import time
import signal
import os
import sys
import uuid
import graphyte
from influxdb_client import Point
import daiquiri
import hupper
from typing import Dict

# App-specific includes
from common.constants import mercure_defs, mercure_names
import common.helper as helper
import common.config as config
import common.monitor as monitor
from routing.route_series import route_series, route_error_files
from routing.route_studies import route_studies
from routing.common import generate_task_id

# Create local logger instance
logger = config.get_logger()
main_loop = None  # type: helper.AsyncTimer # type: ignore


async def terminate_process(signalNumber, frame) -> None:
    """
    Triggers the shutdown of the service
    """
    helper.g_log("events.shutdown", 1)
    helper.g_log_influxdb(
        Point(
            "mercure."
            + config.mercure.appliance_name
            + ".router.main.events.shutdown"
        ).field("value", 1),
        config.mercure.influxdb_host,
        config.mercure.influxdb_token,
        config.mercure.influxdb_org,
        config.mercure.influxdb_bucket,
    )
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def run_router() -> None:
    """
    Main processing function that is called every second
    """
    if helper.is_terminated():
        return

    helper.g_log("events.run", 1)
    helper.g_log_influxdb(
        Point(
            "mercure."
            + config.mercure.appliance_name
            + ".router.main.events.run"
        ).field("value", 1),
        config.mercure.influxdb_host,
        config.mercure.influxdb_token,
        config.mercure.influxdb_org,
        config.mercure.influxdb_bucket,
    )
    # logger.info('')
    # logger.info('Processing incoming folder...')

    try:
        config.read_config()
    except Exception:
        logger.warning(  # handle_error
            "Unable to update configuration. Skipping processing.",
            None,
            event_type=monitor.m_events.CONFIG_UPDATE,
        )
        return

    filecount = 0
    series: Dict[str, float] = {}
    complete_series: Dict[str, float] = {}
    pending_series: Dict[str, float] = {}  # Every series that hasn't timed out yet
    error_files_found = False

    # Check the incoming folder for completed series. To this end, generate a map of all
    # series in the folder with the timestamp of the latest DICOM file as value
    for entry in os.scandir(config.mercure.incoming_folder):
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
        if (time.time() - series[series_entry]) > config.mercure.series_complete_trigger:
            complete_series[series_entry] = series[series_entry]
        else:
            pending_series[series_entry] = series[series_entry]
    # logger.info(f'Files found     = {filecount}')
    # logger.info(f'Series found    = {len(series)}')
    # logger.info(f'Complete series = {len(complete_series)}')
    helper.g_log("incoming.files", filecount)
    helper.g_log_influxdb(
        Point(
            "mercure."
            + config.mercure.appliance_name
            + ".router.main.incoming.files"
        ).field("value", filecount),
        config.mercure.influxdb_host,
        config.mercure.influxdb_token,
        config.mercure.influxdb_org,
        config.mercure.influxdb_bucket,
    )
    helper.g_log("incoming.series", len(series))
    helper.g_log_influxdb(
        Point(
            "mercure."
            + config.mercure.appliance_name
            + ".router.main.incoming.series"
        ).field("value", len(series)),
        config.mercure.influxdb_host,
        config.mercure.influxdb_token,
        config.mercure.influxdb_org,
        config.mercure.influxdb_bucket,
    )

    # Process all complete series
    for series_uid in sorted(complete_series):
        task_id = generate_task_id()
        try:
            route_series(task_id, series_uid)
        except Exception:
            logger.error(f"Problems while processing series {series_uid}", task_id)  # handle_error
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return

    if error_files_found:
        route_error_files()

    # Now, check if studies in the studies folder are ready for routing/processing
    route_studies(pending_series)


def exit_router(args) -> None:
    """
    Callback function that is triggered when the process terminates. Stops the asyncio event loop
    """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


# Main entry point of the router module
def main(args=sys.argv[1:]) -> None:
    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        reloader = hupper.start_reloader("router.main")

    logger.info("")
    logger.info(f"mercure DICOM Router ver {mercure_defs.VERSION}")
    logger.info("--------------------------------------------")
    logger.info("")

    # Register system signals to be caught
    signals = (signal.SIGTERM, signal.SIGINT)
    for s in signals:
        helper.loop.add_signal_handler(s, lambda s=s: asyncio.create_task(terminate_process(s, helper.loop)))

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

    appliance_name = config.mercure.appliance_name

    logger.info(f"Appliance name = {appliance_name}")
    logger.info(f"Instance  name = {instance_name}")
    logger.info(f"Instance  PID  = {os.getpid()}")
    logger.info(sys.version)
    logger.info(f"Mercure Config = {config.mercure}")

    monitor.configure("router", instance_name, config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure.graphite_ip) > 0:
        logger.info(f"Sending events to graphite server: {config.mercure.graphite_ip}")
        graphite_prefix = "mercure." + appliance_name + ".router." + instance_name
        graphyte.init(config.mercure.graphite_ip, config.mercure.graphite_port, prefix=graphite_prefix)

    logger.info(
        f"""Incoming folder: {config.mercure.incoming_folder}
        Studies folder: {config.mercure.studies_folder}
        Outgoing folder: {config.mercure.outgoing_folder}
        Processing folder: {config.mercure.processing_folder}"""
    )

    # Start the timer that will periodically trigger the scan of the incoming folder
    global main_loop
    main_loop = helper.AsyncTimer(config.mercure.router_scan_interval, run_router)

    helper.g_log("events.boot", 1)
    helper.g_log_influxdb(
        Point(
            "mercure."
            + config.mercure.appliance_name
            + ".router.main.events.boot").field("value", 1
            ),
            config.mercure.influxdb_host,
            config.mercure.influxdb_token,
            config.mercure.influxdb_org,
            config.mercure.influxdb_bucket)

    try:
        main_loop.run_until_complete(helper.loop)
        # Process will exit here once the asyncio loop has been stopped
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    except Exception as e:
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.ERROR, str(e))
    finally:
        # Finish all asyncio tasks that might be still pending
        remaining_tasks = helper.asyncio.all_tasks(helper.loop)  # type: ignore[attr-defined]
        if remaining_tasks:
            helper.loop.run_until_complete(helper.asyncio.gather(*remaining_tasks))

    logger.info("Going down now")


if __name__ == "__main__":
    main()
