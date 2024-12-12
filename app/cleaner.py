"""
cleaner.py
==========
The cleaner service of mercure. Responsible for deleting processed data after
retention time has passed and if it is offpeak time. Offpeak is the time
period when the cleaning has to be done, because cleaning I/O should be kept
to minimum when receiving and sending exams.
"""

# Standard python includes
import asyncio
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from shutil import disk_usage, rmtree

# App-specific includes
import common.config as config
import common.helper as helper
import common.influxdb
import common.monitor as monitor
import common.notification as notification
import graphyte
import hupper
from common.constants import mercure_defs
from common.monitor import task_event

# Setup daiquiri logger
logger = config.get_logger()

main_loop = None  # type: helper.AsyncTimer # type: ignore


async def terminate_process(signalNumber, frame) -> None:
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def clean() -> None:
    """Main entry function."""
    if helper.is_terminated():
        return

    helper.g_log("events.run", 1)

    try:
        config.read_config()
    except Exception:
        logger.warning(  # handle_error
            "Unable to read configuration. Skipping processing.",
            None,
            event_type=monitor.m_events.CONFIG_UPDATE,
        )
        return

    # Emergency cleaning procedure: Check if server is running out of disk space. If so, clean images right away

    # Get the percentage of disk usage that should trigger the emergency cleaning
    emergency_clean_trigger: float = config.mercure.emergency_clean_percentage / 100.0

    # Check if the success and discard folder are stored on the same volume
    success_folder = config.mercure.success_folder
    discard_folder = config.mercure.discard_folder
    success_folder_partition = os.stat(success_folder).st_dev
    discard_folder_partition = os.stat(discard_folder).st_dev

    # For emergency cleaning need to take into account if success and discard
    # folders are on the same volume or not.
    emergency_retention = timedelta(0)
    folders_to_clear = [success_folder, discard_folder]
    if success_folder_partition == discard_folder_partition:
        (total, used, _) = disk_usage(success_folder)
        bytes_to_clear = int(max(used - total * emergency_clean_trigger, 0))
        if bytes_to_clear > 0:
            for folder in folders_to_clear:
                # Need to delete all scan data in the both folders to urgently clean up the space.
                clean_dir(folder, emergency_retention)
            monitor.send_event(
                monitor.m_events.PROCESSING,
                monitor.severity.WARNING,
                (f"Disk is almost full. Emergency cleaning of the {success_folder} and {discard_folder} folders."
                 " Consider adjusting retention period."),
            )
    else:
        bytes_to_clear = 0
        for folder in folders_to_clear:
            (total, used, _) = disk_usage(folder)
            bytes_to_clear = int(max(used - total * emergency_clean_trigger, 0))
            if bytes_to_clear > 0:
                # Need to delete all scan data in the folder to urgently clean up the space.
                clean_dir(folder, emergency_retention)
                monitor.send_event(
                    monitor.m_events.PROCESSING,
                    monitor.severity.WARNING,
                    f"Disk is almost full. Emergency cleaning of the {folder} folder. Consider adjusting retention period.",
                )

    # Regular cleaning procedure
    if helper._is_offpeak(
        config.mercure.offpeak_start,
        config.mercure.offpeak_end,
        datetime.now().time(),
    ):
        retention = timedelta(seconds=config.mercure.retention)
        clean_dir(success_folder, retention)
        clean_dir(discard_folder, retention)


def clean_dir(folder, retention) -> None:
    """
    Cleans items from the given folder that have exceeded the retention time, starting with the oldest items
    """
    candidates = [
        (f, f.stat().st_mtime)
        for f in Path(folder).iterdir()
        if f.is_dir() and retention < timedelta(seconds=(time.time() - f.stat().st_mtime))
    ]

    for entry in candidates:
        delete_folder(entry)


def delete_folder(entry) -> None:
    """Deletes given folder."""
    delete_path = entry[0]
    series_uid = find_series_uid(delete_path)
    try:
        rmtree(delete_path)
        logger.info(f"Deleted folder {delete_path} from {series_uid}")
        monitor.send_task_event(task_event.CLEAN, Path(delete_path).stem, 0, delete_path, "Deleted folder")
    except Exception:
        logger.error(
            f"Unable to delete folder {delete_path}",
            Path(delete_path).stem,
            target=delete_path,
        )  # handle_error


def find_series_uid(work_dir) -> str:
    """
    Finds series uid which is always part before the '#'-sign in filename.
    """
    to_be_deleted_dir = Path(work_dir)
    for entry in to_be_deleted_dir.iterdir():
        if "#" in entry.name:
            return entry.name.split(mercure_defs.SEPARATOR)[0]
        return "series_uid-not-found"
    return "series_uid-not-found"


def exit_cleaner(args) -> None:
    """Stop the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


def main(args=sys.argv[1:]) -> None:
    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        hupper.start_reloader("cleaner.main")
        import logging

        logging.getLogger("watchdog").setLevel(logging.WARNING)
    logger.info("")
    logger.info(f"mercure DICOM Cleaner ver {mercure_defs.VERSION}")
    logger.info("--------------------------------------------")
    logger.info("")

    # Register system signals to be caught
    signals = (signal.SIGTERM, signal.SIGINT)
    for s in signals:
        helper.loop.add_signal_handler(s, lambda s=s: asyncio.create_task(terminate_process(s, helper.loop)))

    instance_name = "main"

    if len(sys.argv) > 1:
        instance_name = sys.argv[1]

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

    notification.setup()
    monitor.configure("cleaner", instance_name, config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure.graphite_ip) > 0:
        logger.info(f"Sending events to graphite server: {config.mercure.graphite_ip}")
        graphite_prefix = "mercure." + appliance_name + ".cleaner." + instance_name
        graphyte.init(
            config.mercure.graphite_ip,
            config.mercure.graphite_port,
            prefix=graphite_prefix,
        )

    if len(config.mercure.influxdb_host) > 0:
        logger.info(f"Sending events to influxdb server: {config.mercure.influxdb_host}")
        common.influxdb.init(
            config.mercure.influxdb_host,
            config.mercure.influxdb_token,
            config.mercure.influxdb_org,
            config.mercure.influxdb_bucket,
            "mercure." + appliance_name + ".cleaner." + instance_name
        )

    global main_loop
    main_loop = helper.AsyncTimer(config.mercure.cleaner_scan_interval, clean)
    main_loop.start()

    helper.g_log("events.boot", 1)

    try:
        # Start the asyncio event loop for asynchronous function calls
        main_loop.run_until_complete(helper.loop)
        # Process will exit here once the asyncio loop has been stopped
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    except Exception as e:
        # Process will exit here once the asyncio loop has been stopped
        monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.ERROR, str(e))
    finally:
        # Finish all asyncio tasks that might be still pending
        remaining_tasks = helper.asyncio.all_tasks(helper.loop)  # type: ignore[attr-defined]
        if remaining_tasks:
            helper.loop.run_until_complete(helper.asyncio.gather(*remaining_tasks))

        logger.info("Going down now")


if __name__ == "__main__":
    main()
