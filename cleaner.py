"""
cleaner.py
==========
The cleaner service of mercure. Responsible for deleting processed data after
retention time has passed and if it is offpeak time. Offpeak is the time
period when the cleaning has to be done, because cleaning I/O should be kept
to minimum when receiving and sending exams.
"""
import logging
import os
import signal
import sys
import time
from datetime import timedelta, datetime
from pathlib import Path
from shutil import rmtree
import daiquiri
import graphyte

import common.config as config
import common.helper as helper
import common.monitor as monitor
from common.monitor import send_series_event, s_events
from common.constants import mercure_defs, mercure_folders


daiquiri.setup(
    level=logging.INFO,
    outputs=(daiquiri.output.Stream(formatter=daiquiri.formatter.ColorFormatter(fmt="%(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s")),),
)
logger = daiquiri.getLogger("cleaner")


def terminate_process(signalNumber, frame):
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.h_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def clean(args):
    """ Main entry function. """
    if helper.is_terminated():
        return

    helper.g_log("events.run", 1)

    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to read configuration. Skipping processing.")
        monitor.send_event(
            monitor.h_events.CONFIG_UPDATE,
            monitor.severity.WARNING,
            "Unable to read configuration (possibly locked)",
        )
        return

    # TODO: Adaptively reduce the retention time if the disk space is running low

    if _is_offpeak(
        config.mercure["offpeak_start"],
        config.mercure["offpeak_end"],
        datetime.now().time(),
    ):
        success_folder = config.mercure[mercure_folders.SUCCESS]
        discard_folder = config.mercure[mercure_folders.DISCARD]
        retention = timedelta(seconds=config.mercure["retention"])
        clean_dir(success_folder, retention)
        clean_dir(discard_folder, retention)


def _is_offpeak(offpeak_start, offpeak_end, current_time):
    try:
        start_time = datetime.strptime(offpeak_start, "%H:%M").time()
        end_time = datetime.strptime(offpeak_end, "%H:%M").time()
    except ValueError as e:
        logger.error("Error parsing offpeak time, please check configuration", e)
        return True

    if start_time < end_time:
        return current_time >= start_time and current_time <= end_time
    # End time is after midnight
    return current_time >= start_time or current_time <= end_time


def clean_dir(discard_folder, retention):
    """
    Cleans the discard folder if it is older than the retention time, starting
    from oldest first.
    """
    candidates = [(f, f.stat().st_mtime) for f in Path(discard_folder).iterdir() if f.is_dir() and retention < timedelta(seconds=(time.time() - f.stat().st_mtime))]
    oldest_first = sorted(candidates, key=lambda x: x[1], reverse=True)
    for entry in oldest_first:
        delete_folder(entry)


def delete_folder(entry):
    """ Deletes given folder. """
    delete_path = entry[0]
    series_uid = find_series_uid(delete_path)
    try:
        rmtree(delete_path)
        logger.info(f"Deleted folder {delete_path} from {series_uid}")
        send_series_event(s_events.CLEAN, series_uid, 0, delete_path, "Deleted folder")
    except Exception as e:
        logger.info(f"Unable to delete folder {delete_path}")
        logger.exception(e)
        send_series_event(s_events.ERROR, series_uid, 0, delete_path, "Unable to delete folder")
        monitor.send_event(
            monitor.h_events.PROCESSING,
            monitor.severity.ERROR,
            f"Unable to delete folder {delete_path}",
        )


def find_series_uid(work_dir):
    """
    Finds series uid which is always part before the '#'-sign in filename.
    """
    to_be_deleted_dir = Path(work_dir)
    for entry in to_be_deleted_dir.iterdir():
        if "#" in entry.name:
            return entry.name.split(mercure_defs.SEPARATOR)[0]
        return "series_uid-not-found"


def exit_cleaner(args):
    """ Stop the asyncio event loop. """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == "__main__":
    logger.info("")
    logger.info(f"mercure DICOM Cleaner ver {mercure_defs.VERSION}")
    logger.info("-----------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT, terminate_process)
    signal.signal(signal.SIGTERM, terminate_process)

    instance_name = "main"

    if len(sys.argv) > 1:
        instance_name = sys.argv[1]

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

    monitor.configure("cleaner", instance_name, config.mercure["bookkeeper"])
    monitor.send_event(monitor.h_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure["graphite_ip"]) > 0:
        logger.info(f"Sending events to graphite server: {config.mercure['graphite_ip']}")
        graphite_prefix = "mercure." + appliance_name + ".cleaner." + instance_name
        graphyte.init(
            config.mercure["graphite_ip"],
            config.mercure["graphite_port"],
            prefix=graphite_prefix,
        )

    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure["cleaner_scan_interval"], clean, exit_cleaner, {})
    main_loop.start()

    helper.g_log("events.boot", 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    # Process will exit here once the asyncio loop has been stopped
    monitor.send_event(monitor.h_events.SHUTDOWN, monitor.severity.INFO)
    logger.info("Going down now")
