hermes_dispatcher_version = "0.1a"

import logging
import os
import signal
import sys
import time

import daiquiri

import common.config as config
import common.helper as helper
from dispatcher.send import execute

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("scanner")


def receiveSignal(signalNumber, frame):
    print("Received:", signalNumber)
    return


def terminateProcess(signalNumber, frame):
    helper.triggerTerminate()
    print("Going down now")


def dispatch(args):
    if helper.isTerminated():
        return

    print("")
    print("Processing outgoing folder...")

    try:
        config.read_config()
    except Exception as e:
        print(e)
        print("Unable to update configuration. Skipping processing.")
        return

    print(f"Checking for outgoing data in {config.hermes['outgoing_folder']}")
    with os.scandir(config.hermes["outgoing_folder"]) as it:
        for entry in it:
            print(entry.name)


def exit_dispatcher(args):
    # Stop the asyncio event loop 
    helper.loop.call_soon_threadsafe(helper.loop.stop)

if __name__ == "__main__":
    print("")
    print("Hermes DICOM Dispatcher ver", hermes_dispatcher_version)
    print("----------------------------")
    print("")

    if len(sys.argv) != 2:
        print("Usage: dispatcher.py [configuration file]")
        print("")
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

    print(sys.version)
    print("Router PID is:", os.getpid())

    config.configuration_filename = sys.argv[1]
    try:
        config.read_config()
    except Exception as e:
        print(e)
        print("Cannot start service. Going down.")
        print("")
        sys.exit(1)

    print("Dispatching folder:", config.hermes["outgoing_folder"])

    mainLoop = helper.RepeatedTimer(
        config.hermes["dispatcher_scan_interval"], dispatch, exit_dispatcher,  {}
    )
    mainLoop.start()
