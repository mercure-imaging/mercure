#!/usr/bin/python

# Standard python includes
import time
import signal
import os
import sys
import json
import threading

# App-specific includes
import config

 
# Global variable to broadcast when the process should terminate
terminate=False


# Helper class for running a continuous timer that is suspended
# while the worker function is running
class RepeatedTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer     = None
        self.interval   = interval
        self.function   = function
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False

    def _run(self):
        self.is_running = False
        self.function(*self.args, **self.kwargs)
        global terminate
        if not terminate:            
            self.start()

    def start(self):
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False


def receiveSignal(signalNumber, frame):
    print('Received:', signalNumber)
    return


def terminateProcess(signalNumber, frame):    
    print('Going down now')
    global terminate
    terminate=True


def runRouter(args):
    global terminate
    if terminate:
        return        

    print('')
    print('Parsing folder...')
    config.update_config()

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


if __name__ == '__main__':    
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
   
    config.read_config()
    print('Incoming folder', config.hermes['incoming_folder'])

    mainLoop = RepeatedTimer(config.hermes['update_interval'], runRouter, {})
    mainLoop.start()

