"""
helper.py
=========
Various internal helper functions for mercure.
"""
# Standard python includes
import asyncio
from pathlib import Path
import threading
from typing import Callable, Optional
import graphyte


# Global variable to broadcast when the process should terminate
terminate = False
loop = asyncio.get_event_loop()


def trigger_terminate() -> None:
    """Trigger that the processing loop should terminate after finishing the currently active task."""
    global terminate
    terminate = True


def is_terminated() -> bool:
    """Checks if the process will terminate after the current task."""
    return terminate


async def send_to_graphite(*args, **kwargs) -> None:
    """Wrapper for asynchronous graphite call to avoid wait time of main loop."""
    if graphyte.default_sender == None:
        return
    graphyte.default_sender.send(*args, **kwargs)


def g_log(*args, **kwargs) -> None:
    """Sends diagnostic information to graphite (if configured)."""
    asyncio.run_coroutine_threadsafe(send_to_graphite(*args, **kwargs), loop)


class RepeatedTimer(object):
    """
    Helper class for running a continuous timer that is suspended
    while the worker function is running
    """

    _timer: Optional[threading.Timer]

    def __init__(self, interval: float, function: Callable, exit_function: Callable, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.exit_function = exit_function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False

    def _run(self) -> None:
        """Callback function for the timer event. Will execute the defined function and restart
        the timer after completion, unless the eventloop has been asked to shut down."""
        global terminate
        self.is_running = False
        self.function(*self.args, **self.kwargs)
        if not terminate:
            self.start()
        else:
            self.exit_function(*self.args, **self.kwargs)

    def start(self) -> None:
        """Starts the timer for triggering the calllback after the defined interval."""
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            assert self._timer is not None
            self._timer.start()
            self.is_running = True

    def stop(self) -> None:
        """Stops the timer and executes the defined exit callback function."""
        if self.is_running:
            assert self._timer is not None
            self._timer.cancel()
            self.is_running = False
            self.exit_function(*self.args, **self.kwargs)


class FileLock:
    """Helper class that implements a file lock. The lock file will be removed also from the destructor so that
    no spurious lock files remain if exceptions are raised."""

    def __init__(self, path_for_lockfile: Path):
        self.lockCreated = True
        self.lockfile = path_for_lockfile
        self.lockfile.touch(exist_ok=False)

    # Destructor to ensure that the lock file gets deleted
    # if the calling function is left somewhere as result
    # of an unhandled exception
    def __del__(self) -> None:
        self.free()

    def free(self) -> None:
        if self.lockCreated:
            self.lockfile.unlink()
            self.lockCreated = False
