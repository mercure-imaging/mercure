# Standard python includes
import logging
import os
import signal
import sys
import time
from datetime import timedelta
from pathlib import Path
from shutil import rmtree
import daiquiri
import graphyte

import common.config as config
import common.helper as helper
import common.monitor as monitor
from common.helper import is_ready_for_sending
from common.monitor import send_series_event
from common.monitor import s_events 


hermes_cleaner_version = "0.1a"


daiquiri.setup(
    level=logging.INFO,
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt="%(color)s%(levelname)-8.8s "
                "%(name)s: %(message)s%(color_stop)s"
            )
        ),
    ),
)
logger = daiquiri.getLogger("cleaner")


def receiveSignal(signalNumber, frame):
    logger.info("Received:", signalNumber)
    return


def terminateProcess(signalNumber, frame):
    logger.info("Shutdown requested")
    monitor.send_event(monitor.h_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    helper.triggerTerminate()


def clean(args):
    if helper.isTerminated():
        return
    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to update configuration. Skipping processing.")
        monitor.send_event(monitor.h_events.CONFIG_UPDATE,monitor.severity.WARNING,"Unable to update configuration (possibly locked)")
        return

    success_folder = config.hermes["success_folder"]
    discard_folder = config.hermes["discard_folder"]
    retention = timedelta(seconds=config.hermes["retention"])

    # TODO: Adaptively reduce the retention time if the disk space is running low

    clean_success(success_folder, retention)
    clean_discard(discard_folder, retention)


def clean_discard(discard_folder, retention):
    candidates = [
        (f, f.stat().st_mtime)
        for f in Path(discard_folder).iterdir()
        if f.is_dir()
        and retention < timedelta(seconds=(time.time() - f.stat().st_mtime))
    ]
    oldest_first = sorted(candidates, key=lambda x: x[1], reverse=True)
    for entry in oldest_first:
        series_uid = find_series_uid(entry[0])
        rmtree(entry[0])
        send_series_event(s_events.CLEAN, series_uid, 0, "", "")


def clean_success(success_folder, retention):
    # list of (sent.txt path, modification time)
    candidates = [
        (i, i.stat().st_mtime)
        for i in Path(success_folder).glob("**/sent.txt")
        if retention < timedelta(seconds=(time.time() - i.stat().st_mtime))
    ]
    oldest_first = sorted(candidates, key=lambda x: x[1], reverse=True)
    for entry in oldest_first:
        series_uid = find_series_uid(entry[0])
        rmtree(entry[0].parent)
        send_series_event(s_events.CLEAN, series_uid, 0, "", "")


def find_series_uid(dir):
    to_be_deleted_dir = Path(dir)
    for entry in to_be_deleted_dir.iterdir():
        return entry.name.split("#")[0]


def exit_cleaner(args):
    """ Stop the asyncio event loop. """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == "__main__":
    logger.info("")
    logger.info(f"Hermes DICOM Cleaner ver {hermes_cleaner_version}")
    logger.info("----------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT, terminateProcess)
    signal.signal(signal.SIGQUIT, receiveSignal)
    signal.signal(signal.SIGILL, receiveSignal)
    signal.signal(signal.SIGTRAP, receiveSignal)
    signal.signal(signal.SIGABRT, receiveSignal)
    signal.signal(signal.SIGBUS, receiveSignal)
    signal.signal(signal.SIGFPE, receiveSignal)
    signal.signal(signal.SIGUSR1, receiveSignal)
    signal.signal(signal.SIGSEGV, receiveSignal)
    signal.signal(signal.SIGUSR2, receiveSignal)
    signal.signal(signal.SIGPIPE, receiveSignal)
    signal.signal(signal.SIGALRM, receiveSignal)
    signal.signal(signal.SIGTERM, terminateProcess)

    logger.info(sys.version)
    logger.info(f"Cleaner PID is: {os.getpid()}")

    try:
        config.read_config()
    except Exception:
        logger.exception("Cannot start service. Going down.")
        sys.exit(1)

    monitor.configure('cleaner',"main",config.hermes['bookkeeper'])
    monitor.send_event(monitor.h_events.BOOT,monitor.severity.INFO,f'PID = {os.getpid()}')

    graphite_prefix = "hermes.cleaner.main"

    if len(config.hermes["graphite_ip"]) > 0:
        logger.info(
            f"Sending events to graphite server: {config.hermes['graphite_ip']}"
        )
        graphyte.init(
            config.hermes["graphite_ip"],
            config.hermes["graphite_port"],
            prefix=graphite_prefix,
        )

    mainLoop = helper.RepeatedTimer(
        config.hermes["cleaner_scan_interval"], clean, exit_cleaner, {}
    )
    mainLoop.start()

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    monitor.send_event(monitor.h_events.SHUTDOWN, monitor.severity.INFO)
    logger.info("Going down now")
