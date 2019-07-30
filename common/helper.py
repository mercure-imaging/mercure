import graphyte
import threading
import sys
import asyncio 
import functools


# Global variable to broadcast when the process should terminate
terminate=False
loop=asyncio.get_event_loop() 

def triggerTerminate():
    global terminate
    terminate=True


def isTerminated():
    return terminate


# Wrapper for asynchronous graphite call to avoid wait time of main loop
async def sendToGraphite(*args, **kwargs):
    if (graphyte.default_sender==None):
        return
    graphyte.default_sender.send(*args, **kwargs)


def g_log(*args, **kwargs):
    asyncio.run_coroutine_threadsafe(sendToGraphite(*args, **kwargs),loop)


# Helper class for running a continuous timer that is suspended
# while the worker function is running
class RepeatedTimer(object):
    def __init__(self, interval, function, exit_function, *args, **kwargs):
        self._timer        = None
        self.interval      = interval
        self.function      = function
        self.exit_function = exit_function
        self.args          = args
        self.kwargs        = kwargs
        self.is_running    = False

    def _run(self):
        global terminate
        self.is_running = False
        self.function(*self.args, **self.kwargs)
        if not terminate:            
            self.start()
        else:
            self.exit_function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False
        self.exit_function(*self.args, **self.kwargs)
