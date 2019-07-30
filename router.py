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

# App-specific includes
import common.helper as helper
import common.config as config


loop = asyncio.get_event_loop() 


def receiveSignal(signalNumber, frame):
    print('Received:', signalNumber)
    return


def terminateProcess(signalNumber, frame):    
    helper.triggerTerminate()
    print('Going down now')


def runRouter(args):
    if helper.isTerminated():
        return        

    print('')
    print('Processing incoming folder...')
    
    try:
        config.read_config()
    except Exception as e: 
        print(e)
        print("Unable to update configuration. Skipping processing.")
        return

    filecount=0
    series={}
    completeSeries={}

    for entry in os.scandir(config.hermes['incoming_folder']):
            if not entry.name.endswith(".tags") and not entry.is_dir():
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
    
    for entry in sorted(completeSeries):
        pass
        #print(completeSeries[entry])


def exitRouter(args):
    # Stop the asyncio event loop 
    loop.call_soon_threadsafe(loop.stop)


if __name__ == '__main__':    
    print("")
    print("Hermes DICOM Router ver", hermes_router_version)
    print("----------------------------")
    print("")

    if (len(sys.argv) != 2):
        print("Usage: router.py [configuration file]")
        print("")
        sys.exit()

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

    print(sys.version)
    print('Router PID is:', os.getpid())
   
    config.configuration_filename=sys.argv[1]
    try:
        config.read_config()
    except Exception as e: 
        print(e)
        print("Cannot start service. Going down.")
        print("")
        sys.exit(1)

    if len(config.hermes['graphite_ip']) > 0:
        graphyte.init(config.hermes['graphite_ip'], config.hermes['graphite_port'], prefix='hermes.router')

    #helper.g_log('foo.bar', 42)

    print('Incoming folder:', config.hermes['incoming_folder'])

    mainLoop = helper.RepeatedTimer(config.hermes['router_update_interval'], runRouter, exitRouter, {})
    mainLoop.start()

    # Start the asyncio event loop for asynchronous function calls
    loop.run_forever()
