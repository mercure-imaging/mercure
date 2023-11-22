"""
helper.py
=========
Various internal helper functions for mercure.
"""
# Standard python includes
import asyncio
from contextlib import suppress
import inspect
from pathlib import Path
import threading
from typing import Callable, Optional
import graphyte
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import ASYNCHRONOUS
import aiohttp
import os

# Global variable to broadcast when the process should terminate
terminate = False


loop = asyncio.get_event_loop()


def get_runner() -> str:
    """Returns the name of the mechanism that is used for running mercure in the current installation (systemd, docker, nomad)."""
    return os.getenv("MERCURE_RUNNER", "systemd")


def trigger_terminate() -> None:
    """Trigger that the processing loop should terminate after finishing the currently active task."""
    global terminate
    terminate = True


def is_terminated() -> bool:
    """Checks if the process will terminate after the current task."""
    return terminate


def send_to_graphite(*args, **kwargs) -> None:
    """Wrapper for asynchronous graphite call to avoid wait time of main loop."""
    if graphyte.default_sender == None:
        return
    graphyte.default_sender.send(*args, **kwargs)


def send_to_influxdb(data_point, bucket, write_api) -> None:
    """Wrapper for asynchronous InfluxDB call to avoid wait time of main loop."""
    write_api.write(bucket=bucket, record=data_point)


def g_log(*args, **kwargs) -> None:
    global loop
    """Sends diagnostic information to graphite (if configured)."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(send_to_graphite, *args, **kwargs)
    except:
        send_to_graphite(*args, **kwargs)


def g_log_influxdb(data_point, host, token, org, bucket) -> None:
    global loop
    """Sends diagnostic information to graphite (if configured)."""
    # Initialize InfluxDB client
    if len(host) > 0:
        client = InfluxDBClient(
            url=host,
            token=token,
            org=org,
        )
        write_api = client.write_api(write_options=ASYNCHRONOUS)
    else:
        return
    
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(send_to_influxdb, data_point)
    except:
        send_to_influxdb(data_point, bucket, write_api)


class AsyncTimer(object):
    def __init__(self, interval: int, func):
        self.func = func
        self.time = interval
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            # Start task to call func periodically:
            self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        """Signal to stop after the current"""
        self.is_running = False

    async def _run(self) -> None:
        global terminate
        while self.is_running:
            await asyncio.sleep(self.time)
            if terminate:
                self.stop()

            if not self.is_running:
                break

            if inspect.isawaitable(res := self.func()):
                await res

    def run_until_complete(self, loop=None) -> None:
        self.start()
        loop = loop or asyncio.get_event_loop()
        loop.run_until_complete(self._task)


class RepeatedTimer(object):
    """
    Helper class for running a continuous timer that is suspended
    while the worker function is running
    """

    _timer: Optional[threading.Timer]

    def __init__(
        self,
        interval: float,
        function: Callable,
        exit_function: Callable,
        *args,
        **kwargs,
    ):
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
        self.lockfile = path_for_lockfile
        # TODO: Handle case if lock file cannot be created
        self.lockfile.touch(exist_ok=False)
        self.lockCreated = True

    # Destructor to ensure that the lock file gets deleted
    # if the calling function is left somewhere as result
    # of an unhandled exception
    def __del__(self) -> None:
        self.free()

    def free(self) -> None:
        if self.lockCreated:
            self.lockfile.unlink()
            self.lockCreated = False
