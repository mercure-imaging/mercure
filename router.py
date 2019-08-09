#!/usr/bin/python
hermes_router_version = "0.1a"

# Standard python includes
import time
import signal
import os
import sys
import json
import graphyte
import asyncio
import threading
import logging

# 3rd party
import daiquiri

# App-specific includes
import common.helper as helper
import common.config as config
from router.process_series import process_series

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("router")

# NOTES: Currently, the router only implements series-level rules, i.e. the proxy rules will be executed
#        once the series is complete. In the future, also study-level rules can be implemented (i.e. a
#        rule can be a series-level or study-level rule). Series-level rules are executed as done right now.
#        If a study-level rule exists that applies to a series, the series will be moved to an /incoming-study
#        folder and renamed with the studyUID as prefix. Once the study is complete (via a separate time
#        tigger), the study-level rules will be applied by taking each rule and collecting the series of
#        the studies that apply to the rule. Each study-level rule will create a separate outgoing folder
#        so that all series that apply to the study-level rule are transferred together in one DICOM
#        transfer (association). This might be necessary for certain PACS systems or workstations (e.g.
#        when transferring 4D series).


def receiveSignal(signalNumber, frame):
    logger.info(f'Received: {signalNumber}')
    return


def terminateProcess(signalNumber, frame):
    helper.g_log('events.shutdown', 1)
    logger.info('Shutdown requested')
    helper.triggerTerminate()


def runRouter(args):
    if helper.isTerminated():
        return

    helper.g_log('events.run', 1)

    logger.info('')
    logger.info('Processing incoming folder...')

    try:
        config.read_config()
    except Exception as e:
        logger.error(e)
        logger.error("Unable to update configuration. Skipping processing.")
        # TODO: Send error notification!
        return

    filecount=0
    series={}
    completeSeries={}

    for entry in os.scandir(config.hermes['incoming_folder']):
            if entry.name.endswith(".tags") and not entry.is_dir():
                filecount += 1
                seriesString=entry.name.split('#',1)[0]
                modificationTime=entry.stat().st_mtime

                if seriesString in series.keys():
                    if modificationTime > series[seriesString]:
                        series[seriesString]=modificationTime
                else:
                    series[seriesString]=modificationTime

    for entry in series:
        if ((time.time()-series[entry]) > config.hermes['series_complete_trigger']):
            completeSeries[entry]=series[entry]

    logger.info(f'Files found     = {filecount}')
    logger.info(f'Series found    = {len(series)}')
    logger.info(f'Complete series = {len(completeSeries)}')
    helper.g_log('incoming.files', filecount)
    helper.g_log('incoming.series', len(series))

    for entry in sorted(completeSeries):
        try:
            process_series(entry)
        except Exception as e:
            logger.error(e)
            logger.error(f'ERROR: Problems while processing series {entry}')
        # If termination is requested, stop processing series after the active one has been completed
        if helper.isTerminated():
            break

def exitRouter(args):
    # Stop the asyncio event loop
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == '__main__':
    logger.info("")
    logger.info(f"Hermes DICOM Router ver {hermes_router_version}")
    logger.info("----------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT,   terminateProcess)
    signal.signal(signal.SIGQUIT,  receiveSignal)
    signal.signal(signal.SIGILL,   receiveSignal)
    signal.signal(signal.SIGTRAP,  receiveSignal)
    signal.signal(signal.SIGABRT,  receiveSignal)
    signal.signal(signal.SIGBUS,   receiveSignal)
    signal.signal(signal.SIGFPE,   receiveSignal)
    signal.signal(signal.SIGUSR1,  receiveSignal)
    signal.signal(signal.SIGSEGV,  receiveSignal)
    signal.signal(signal.SIGUSR2,  receiveSignal)
    signal.signal(signal.SIGPIPE,  receiveSignal)
    signal.signal(signal.SIGALRM,  receiveSignal)
    signal.signal(signal.SIGTERM,  terminateProcess)
    #signal.signal(signal.SIGHUP,  readConfiguration)
    #signal.signal(signal.SIGKILL, receiveSignal)

    instance_name="main"

    if len(sys.argv)>1:
        instance_name=sys.argv[1]

    logger.info(sys.version)
    logger.info(f'Instance name = {instance_name}')
    logger.info(f'Instance PID = {os.getpid()}')

    try:
        config.read_config()
    except Exception as e:
        logger.error(e)
        logger.error("Cannot start service. Going down.")
        logger.error("")
        sys.exit(1)

    graphite_prefix='hermes.router.'+instance_name

    if len(config.hermes['graphite_ip']) > 0:
        logger.info(f'Sending events to graphite server: {config.hermes["graphite_ip"]}')
        graphyte.init(config.hermes['graphite_ip'], config.hermes['graphite_port'], prefix=graphite_prefix)

    logger.info(f'Incoming folder: {config.hermes["incoming_folder"]}')
    logger.info(f'Outgoing folder: {config.hermes["outgoing_folder"]}')

    mainLoop = helper.RepeatedTimer(config.hermes['router_scan_interval'], runRouter, exitRouter, {})
    mainLoop.start()

    helper.g_log('events.boot', 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()
    logger.info('Going down now')
