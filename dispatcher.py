"""
dispatcher.py
=============
The dispatcher service of mercure that executes the DICOM transfer to the different targets.
"""

# Standard python includes
import logging
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


# Create local logger instance
logger = config.get_logger()
main_loop = None  # type: helper.RepeatedTimer # type: ignore


dispatcher_lockfile = None
dispatcher_is_locked = False


def terminate_process(signalNumber, frame) -> None:
    """Triggers the shutdown of the service."""
    helper.g_log("events.shutdown", 1)
    logger.info("Shutdown requested")
    monitor.send_event(monitor.m_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if "main_loop" in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def dispatch(args) -> None:
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

    # Obtain a sorted folder list, so that the oldest DICOMs get dispatched first
    items = sorted(Path(config.mercure.outgoing_folder).iterdir(), key=os.path.getmtime)
    for entry in items:
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

        # Now process the folders that are ready for dispatching
        if entry.is_dir() and is_ready_for_sending(entry):
            execute(Path(entry), success_folder, error_folder, retry_max, retry_delay)

        # If termination is requested, stop processing series after the
        # active one has been completed
        if helper.is_terminated():
            break


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

    appliance_name = config.mercure.appliance_name

    logger.info(f"Appliance name = {appliance_name}")
    logger.info(f"Instance  name = {instance_name}")
    logger.info(f"Instance  PID  = {os.getpid()}")
    logger.info(sys.version)

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

    logger.info(f"Dispatching folder: {config.mercure.outgoing_folder}")
    dispatcher_lockfile = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)

    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure.dispatcher_scan_interval, dispatch, exit_dispatcher, {})
    main_loop.start()

    helper.g_log("events.boot", 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO)
    logging.info("Going down now")


if __name__ == "__main__":
    main()
