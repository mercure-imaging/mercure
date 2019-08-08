# Standard python includes
import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import daiquiri
import graphyte

import common.config as config
import common.helper as helper

hermes_cleaner_version = "0.1a"

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("cleaner")


def receiveSignal(signalNumber, frame):
    logger.info("Received:", signalNumber)
    return


def terminateProcess(signalNumber, frame):
    print("Shutdown requested")
    helper.triggerTerminate()


def clean(args):
    if helper.isTerminated():
        return
    try:
        config.read_config()
    except Exception as e:
        logger.info(e)
        logger.info("Unable to update configuration. Skipping processing.")
        return

    success_folder = config.hermes["success_folder"]
    discard_folder = config.hermes["discard_folder"]
    retention = timedelta(seconds=config.hermes["retention"])
    
    clean_dirs = [success_folder, discard_folder]
    logger.info(f"Checking for cleaning data in {clean_dirs}")

    candidates = [
        (i, retention < timedelta(seconds=(time.time() - i.stat().st_mtime)))
        for i in Path(success_folder).glob("**/sent.txt")
    ]
    print(candidates)


def exit_cleaner(args):
    """ Stop the asyncio event loop. """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == "__main__":
    logger.info("")
    logger.info("Hermes DICOM Cleaner ver", hermes_cleaner_version)
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
    except Exception as e:
        logger.info(e)
        logger.info("Cannot start service. Going down.")
        logger.info("")
        sys.exit(1)

    graphite_prefix = "hermes.cleaner.main"

    if len(config.hermes["graphite_ip"]) > 0:
        print("Sending events to graphite server: ", config.hermes["graphite_ip"])
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
    print("Going down now")
