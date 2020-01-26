"""
router.py
=========
mercure' central router module that evaluates the routing rules and decides which series should be sent to which target. 
"""
# Standard python includes
import time
import signal
import os
import sys
import graphyte
import logging
import daiquiri

# App-specific includes
import common.helper as helper
import common.config as config
import common.monitor as monitor
import common.version as version
from routing.route_series import route_series
from routing.route_series import route_error_files


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
logger = daiquiri.getLogger("router")


def terminate_process(signalNumber, frame):
    """Triggers the shutdown of the service."""
    helper.g_log('events.shutdown', 1)
    logger.info('Shutdown requested')
    monitor.send_event(monitor.h_events.SHUTDOWN_REQUEST, monitor.severity.INFO)
    # Note: main_loop can be read here because it has been declared as global variable
    if 'main_loop' in globals() and main_loop.is_running:
        main_loop.stop()
    helper.trigger_terminate()


def run_router(args):
    """Main processing function that is called every second."""
    if helper.is_terminated():
        return

    helper.g_log('events.run', 1)

    #logger.info('')
    #logger.info('Processing incoming folder...')

    try:
        config.read_config()
    except Exception:
        logger.exception("Unable to update configuration. Skipping processing.")
        monitor.send_event(monitor.h_events.CONFIG_UPDATE,monitor.severity.WARNING,"Unable to update configuration (possibly locked)")
        return

    filecount=0
    series={}
    completeSeries={}

    error_files_found = False

    # Check the incoming folder for completed series. To this end, generate a map of all
    # series in the folder with the timestamp of the latest DICOM file as value
    for entry in os.scandir(config.mercure['incoming_folder']):
        if entry.name.endswith(".tags") and not entry.is_dir():
            filecount += 1
            seriesString=entry.name.split('#',1)[0]
            modificationTime=entry.stat().st_mtime

            if seriesString in series.keys():
                if modificationTime > series[seriesString]:
                    series[seriesString]=modificationTime
            else:
                series[seriesString]=modificationTime
        # Check if at least one .error file exists. In that case, the incoming folder should
        # be searched for .error files at the end of the update run
        if (not error_files_found) and entry.name.endswith(".error"):
            error_files_found = True

    # Check if any of the series exceeds the "series complete" threshold
    for entry in series:
        if ((time.time()-series[entry]) > config.mercure['series_complete_trigger']):
            completeSeries[entry]=series[entry]

    #logger.info(f'Files found     = {filecount}')
    #logger.info(f'Series found    = {len(series)}')
    #logger.info(f'Complete series = {len(completeSeries)}')
    helper.g_log('incoming.files', filecount)
    helper.g_log('incoming.series', len(series))

    # Process all complete series
    for entry in sorted(completeSeries):
        try:
            route_series(entry)
        except Exception:
            logger.exception(f'Problems while processing series {entry}')
            monitor.send_series_event(monitor.s_events.ERROR, entry, 0, "", "Exception while processing")
            monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, "Exception while processing series")
        # If termination is requested, stop processing series after the active one has been completed
        if helper.is_terminated():
            return

    if error_files_found:
        route_error_files()


def exit_router(args):
    """Callback function that is triggered when the process terminates. Stops the asyncio event loop."""
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == '__main__':
    logger.info("")
    logger.info(f"mercure DICOM Router ver {version.mercure_version}")
    logger.info("-----------------------------")
    logger.info("")

    # Register system signals to be caught
    signal.signal(signal.SIGINT,   terminate_process)
    signal.signal(signal.SIGTERM,  terminate_process)

    instance_name="main"

    if len(sys.argv)>1:
        instance_name=sys.argv[1]

    # Read the configuration file and terminate if it cannot be read
    try:
        config.read_config()
    except Exception:
        logger.exception("Cannot start service. Going down.")
        sys.exit(1)

    appliance_name=config.mercure['appliance_name']

    logger.info(f'Appliance name = {appliance_name}')
    logger.info(f'Instance  name = {instance_name}')
    logger.info(f'Instance  PID  = {os.getpid()}')
    logger.info(sys.version)

    monitor.configure('router',instance_name,config.mercure['bookkeeper'])
    monitor.send_event(monitor.h_events.BOOT,monitor.severity.INFO,f'PID = {os.getpid()}')

    graphite_prefix='mercure.'+appliance_name+'.router.'+instance_name

    if len(config.mercure['graphite_ip']) > 0:
        logger.info(f'Sending events to graphite server: {config.mercure["graphite_ip"]}')
        graphyte.init(config.mercure['graphite_ip'], config.mercure['graphite_port'], prefix=graphite_prefix)

    logger.info(f'Incoming folder:   {config.mercure["incoming_folder"]}')
    logger.info(f'Outgoing folder:   {config.mercure["outgoing_folder"]}')
    logger.info(f'Processing folder: {config.mercure["processing_folder"]}')

    # Start the timer that will periodically trigger the scan of the incoming folder
    global main_loop
    main_loop = helper.RepeatedTimer(config.mercure['router_scan_interval'], run_router, exit_router, {})
    main_loop.start()

    helper.g_log('events.boot', 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()

    # Process will exit here once the asyncio loop has been stopped
    monitor.send_event(monitor.h_events.SHUTDOWN, monitor.severity.INFO)
    logger.info('Going down now')
