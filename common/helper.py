import graphyte
import threading
import sys


# Global variable to broadcast when the process should terminate
terminate=False


def triggerTerminate():
    global terminate
    terminate=True


def isTerminated():
    return terminate


def g_log(*args, **kwargs):
    if (graphyte.default_sender==None):
        return
    graphyte.default_sender.send(*args, **kwargs)


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
        global terminate
        self.is_running = False
        self.function(*self.args, **self.kwargs)
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
