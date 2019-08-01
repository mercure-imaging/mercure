"""
dispatcher.py
====================================
The dispatching module of the proxy.
"""
import logging
import os
import signal
import sys
import time
from pathlib import Path

import daiquiri

import common.config as config
import common.helper as helper
from common.helper import has_been_send, is_ready_for_sending
from dispatch.send import execute

# Dispatcher version
hermes_dispatcher_version = "0.1a"

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("dispatcher")


def receiveSignal(signalNumber, frame):
    logger.info("Received:", signalNumber)
    return


def terminateProcess(signalNumber, frame):
    helper.triggerTerminate()
    logger.info("Going down now")


def dispatch(args):
    if helper.isTerminated():
        return
    try:
        config.read_config()
    except Exception as e:
        logger.info(e)
        logger.info("Unable to update configuration. Skipping processing.")
        return

    logger.info(f"Checking for outgoing data in {config.hermes['outgoing_folder']}")
    success_folder = config.hermes["success_folder"]
    error_folder = config.hermes["error_folder"]
    with os.scandir(config.hermes["outgoing_folder"]) as it:
        for entry in it:
            if (
                entry.is_dir()
                and not has_been_send(entry.path)
                and is_ready_for_sending(entry.path)
            ):
                logger.info(f"Sending folder {entry.path}")
                execute(entry.path, success_folder, error_folder)


def exit_dispatcher(args):
    """ Stop the asyncio event loop. """
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == "__main__":
    logger.info("")
    logger.info(f"Hermes DICOM Dispatcher ver {hermes_dispatcher_version}")
    logger.info("----------------------------")
    logger.info("")

    if len(sys.argv) != 2:
        logger.info("Usage: dispatcher.py [configuration file]")
        logger.info("")
        sys.exit()

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
    # signal.signal(signal.SIGHUP,  readConfiguration)
    # signal.signal(signal.SIGKILL, receiveSignal)

    logger.info(sys.version)
    logger.info("Router PID is:", os.getpid())

    config.configuration_filename = sys.argv[1]
    try:
        config.read_config()
    except Exception as e:
        logger.info(e)
        logger.info("Cannot start service. Going down.")
        logger.info("")
        sys.exit(1)

    logger.info(f"Dispatching folder: {config.hermes['outgoing_folder']}")

    mainLoop = helper.RepeatedTimer(
        config.hermes["dispatcher_scan_interval"], dispatch, exit_dispatcher, {}
    )
    mainLoop.start()
