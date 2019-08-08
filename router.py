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

# App-specific includes
import common.helper as helper
import common.config as config
from router.process_series import process_series


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
    print('Received:', signalNumber)
    return


def terminateProcess(signalNumber, frame):    
    helper.g_log('events.shutdown', 1)
    print('Shutdown requested')
    helper.triggerTerminate()


def runRouter(args):
    if helper.isTerminated():
        return        

    helper.g_log('events.run', 1)

    print('')
    print('Processing incoming folder...')
    
    try:
        config.read_config()
    except Exception as e: 
        print(e)
        print("Unable to update configuration. Skipping processing.")
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

    print('Files found     = ',filecount)
    print('Series found    = ',len(series))
    print('Complete series = ',len(completeSeries))
    helper.g_log('incoming.files', filecount)
    helper.g_log('incoming.series', len(series))
    
    for entry in sorted(completeSeries):
        try:
            process_series(entry)
        except Exception as e: 
            print(e)
            print('ERROR: Problems while processing series ', entry)
        # If termination is requested, stop processing series after the active one has been completed
        if helper.isTerminated():
            break                 

def exitRouter(args):
    # Stop the asyncio event loop 
    helper.loop.call_soon_threadsafe(helper.loop.stop)


if __name__ == '__main__':    
    print("")
    print("Hermes DICOM Router ver", hermes_router_version)
    print("----------------------------")
    print("")

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

    print(sys.version)
    print('Instance name = ',instance_name)
    print('Instance PID = ', os.getpid())

    try:
        config.read_config()
    except Exception as e: 
        print(e)
        print("Cannot start service. Going down.")
        print("")
        sys.exit(1)

    graphite_prefix='hermes.router.'+instance_name
    
    if len(config.hermes['graphite_ip']) > 0:
        print('Sending events to graphite server: ',config.hermes['graphite_ip'])
        graphyte.init(config.hermes['graphite_ip'], config.hermes['graphite_port'], prefix=graphite_prefix)   

    print('Incoming folder:', config.hermes['incoming_folder'])
    print('Outgoing folder:', config.hermes['outgoing_folder'])    

    mainLoop = helper.RepeatedTimer(config.hermes['router_scan_interval'], runRouter, exitRouter, {})
    mainLoop.start()

    helper.g_log('events.boot', 1)

    # Start the asyncio event loop for asynchronous function calls
    helper.loop.run_forever()
    print('Going down now')
