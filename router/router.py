#!/usr/bin/python

import time
import signal
import os
import sys
import json
import pyinotify

import config

terminate=False

def receiveSignal(signalNumber, frame):
    print('Received:', signalNumber)
    return


def terminateProcess(signalNumber, frame):    
    #print('Termination request:', signalNumber)
    #print('Going down now')
    #sys.exit()
    global terminate
    terminate=True


if __name__ == '__main__':
    # register the signals to be caught
    #signal.signal(signal.SIGHUP, readConfiguration)
    signal.signal(signal.SIGINT, terminateProcess)
    signal.signal(signal.SIGQUIT, receiveSignal)
    signal.signal(signal.SIGILL, receiveSignal)
    signal.signal(signal.SIGTRAP, receiveSignal)
    signal.signal(signal.SIGABRT, receiveSignal)
    signal.signal(signal.SIGBUS, receiveSignal)
    signal.signal(signal.SIGFPE, receiveSignal)
    #signal.signal(signal.SIGKILL, receiveSignal)
    signal.signal(signal.SIGUSR1, receiveSignal)
    signal.signal(signal.SIGSEGV, receiveSignal)
    signal.signal(signal.SIGUSR2, receiveSignal)
    signal.signal(signal.SIGPIPE, receiveSignal)
    signal.signal(signal.SIGALRM, receiveSignal)
    signal.signal(signal.SIGTERM, terminateProcess)

    print(sys.version)
    # output current process id
    print('My PID is:', os.getpid())
    
    config.read_config()

    print('Path to monitor ', config.hermes['input_folder'])

    class EventHandler(pyinotify.ProcessEvent):
        def process_IN_CREATE(self, event):
            print("Created: ", event.pathname)
            global terminate
            while True:
                print("Doing something...")
                for x in range(10): 
                    #print('Step :',x)
                    if terminate:
                        print('Request to go down after loop')
                if terminate:
                    print('Now going down')
                    sys.exit()


    wm = pyinotify.WatchManager()
    mask = pyinotify.ALL_EVENTS    
    handler = EventHandler()
    notifier = pyinotify.Notifier(wm, handler)
    wdd = wm.add_watch(config.hermes['input_folder'], mask, rec=False)

    notifier.loop()
