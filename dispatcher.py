"""
dispatcher.py
=============
The dispatcher service of mercure that executes the DICOM transfer to the different targets.
"""

# Standard python includes
import asyncio
import logging
import json
import os
import signal
import sys
from pathlib import Path
import daiquiri
import graphyte
import hupper

# App-specific includes
import common.config as config
import common.helper as helper
import common.monitor as monitor
from common.constants import mercure_names
from dispatch.status import is_ready_for_sending
from dispatch.send import execute
from common.constants import mercure_defs
import common.influxdb
import common.notification as notification
from common.types import Task


# Create local logger instance
logger = config.get_logger()
main_loop = None  # type: helper.AsyncTimer # type: ignore


dispatcher_lockfile = None
dispatcher_is_locked = False


async def terminate_process(signalNumber, frame) -> None:
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def dispatch() -> None:
    global dispatcher_lockfile
    global dispatcher_is_locked

    """Main entry function."""
    if helper.is_terminated():
        return

    helper.g_log("events.run", 1)

    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to read configuration. Skipping processing.")
        monitor.send_event(
            monitor.m_events.CONFIG_UPDATE,
            monitor.severity.WARNING,
            "Unable to read configuration (possibly locked)",
        )
        return

    success_folder = Path(config.mercure.success_folder)
    error_folder = Path(config.mercure.error_folder)
    retry_max = config.mercure.retry_max
    retry_delay = config.mercure.retry_delay

    def is_urgent(task_folder: Path) -> bool:
        try:
            taskfile_path = task_folder / mercure_names.TASKFILE
            with open(taskfile_path, "r") as f:
                task_instance = Task(**json.load(f))
            applied_rule = config.mercure.rules.get(task_instance.info.get("applied_rule"))
            if applied_rule is None:
                triggered_rule_names = task_instance.info.get("triggered_rules")
                for rule_name in triggered_rule_names:
                    if config.mercure.rules.get(rule_name).get("priority") == "urgent":
                        return True
                return False
            return applied_rule.get("priority") == "urgent"
        except:
            logger.exception("Error while checking if task is urgent")
            return False

    try:
        items = Path(config.mercure.outgoing_folder).iterdir()
        # Get the folders that are ready for dispatching
        valid_items = [item for item in items if item.is_dir() and is_ready_for_sending(item)]
        # Sort the folders with first urgent priority then modification_time
        sort_key = lambda x: (not is_urgent(x), os.path.getmtime(x))
        sorted_items = sorted(valid_items, key=sort_key)
        for entry in sorted_items:
            # First, check if dispatching might have been suspended via the UI
            if dispatcher_lockfile and dispatcher_lockfile.exists():
                if not dispatcher_is_locked:
                    dispatcher_is_locked = True
                    logger.info(f"Dispatching halted")
                break
            else:
                if dispatcher_is_locked:
                    dispatcher_is_locked = False
                    logger.info("Dispatching resumed")

            execute(Path(entry), success_folder, error_folder, retry_max, retry_delay)

            # If termination is requested, stop processing series after the
            # active one has been completed
            if helper.is_terminated():
                break
    except:
        logger.exception("Error while dispatching")
        return    


def exit_dispatcher(args) -> None:
    """Stop the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


def main(args=sys.argv[1:]) -> None:
    global dispatcher_lockfile

    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        reloader = hupper.start_reloader("dispatcher.main")
    logger.info("")
    logger.info(f"mercure DICOM Dispatcher ver {mercure_defs.VERSION}")
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
    monitor.configure("dispatcher", instance_name, config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")

    if len(config.mercure.graphite_ip) > 0:
        logging.info(f"Sending events to graphite server: {config.mercure.graphite_ip}")
        graphite_prefix = "mercure." + appliance_name + ".dispatcher." + instance_name
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
            "mercure." + appliance_name + ".dispatcher." + instance_name
        )
    
    logger.info(f"Dispatching folder: {config.mercure.outgoing_folder}")
    dispatcher_lockfile = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)

    global main_loop
    main_loop = helper.AsyncTimer(config.mercure.dispatcher_scan_interval, dispatch)

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

        logging.info("Going down now")


if __name__ == "__main__":
    main()
