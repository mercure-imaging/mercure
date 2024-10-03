"""
helper.py
=========
Various internal helper functions for mercure.
"""
# Standard python includes
import asyncio
from datetime import datetime
from datetime import time as _time
import inspect
from pathlib import Path
import re
import threading
from typing import Callable, List, Optional, Tuple
import dateutil
import graphyte
import os
import common.influxdb

# Global variable to broadcast when the process should terminate
terminate = False


loop = asyncio.get_event_loop()

def validate_folders(config) -> Tuple[bool, str]:
    for folder in ( config.incoming_folder, config.studies_folder, config.outgoing_folder,
                    config.success_folder, config.error_folder, config.discard_folder,
                    config.processing_folder, config.jobs_folder ):
        if not Path(folder).is_dir():
            try:
                Path(folder).mkdir(parents=False)
                print(f"Created directory: {folder}")
            except Exception as e:
                return False, f"Folder {folder} does not exist."
            
        if not os.access( folder, os.R_OK | os.W_OK ):
            return False, f"No read/write access to {folder}"
    return True, ""


def localize_log_timestamps(loglines: List[str], config) -> None:
    if config.mercure.local_time == "UTC":
        return
    try:
        local_tz: datetime.tzinfo = dateutil.tz.gettz(config.mercure.local_time)
    except:
        return

    timestamp_pattern = re.compile(r'^(\S+)')

    for i, line in enumerate(loglines):
        match = timestamp_pattern.match(line)
        if not match:
            continue

        timestamp = match.group(1)
        try:
            parsed_dt = dateutil.parser.isoparse(timestamp)
            dt_localtime: datetime.datetime = parsed_dt.astimezone(local_tz)
            localized_timestamp = dt_localtime.isoformat(timespec='seconds')
            loglines[i] = timestamp_pattern.sub(localized_timestamp, line)
        except:
            pass

def get_now_str() -> str:
    """Returns the current time as string with mercure-wide formatting"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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


def send_to_influxdb(*args, **kwargs) -> None:
    """Wrapper for asynchronous influxdb call to avoid wait time of main loop."""
    if common.influxdb.default_sender is None:
        return
    common.influxdb.default_sender.send(*args, **kwargs)


def g_log(*args, **kwargs) -> None:
    global loop
    """Sends diagnostic information to graphite (if configured)."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(send_to_graphite, *args, **kwargs)
        loop.call_soon(send_to_influxdb, *args, **kwargs)
    except:
        send_to_graphite(*args, **kwargs)
        send_to_influxdb(*args, **kwargs)


def _is_offpeak(offpeak_start: str, offpeak_end: str, current_time: _time) -> bool:
    """Check if the provided time is within the offpeak time range."""
    try:
        start_time = datetime.strptime(offpeak_start, "%H:%M").time()
        end_time = datetime.strptime(offpeak_end, "%H:%M").time()
    except Exception as e:
        print(f"Unable to parse offpeak time: {offpeak_start}, {offpeak_end}", None)  # handle_error
        return True

    if start_time < end_time:
        return current_time >= start_time and current_time <= end_time
    # End time is after midnight
    return current_time >= start_time or current_time <= end_time


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
        if not self._task:
            raise Exception("Unexpected error: AsyncTimer._task is None")
        loop = loop or asyncio.get_event_loop()
        loop.run_until_complete(self._task)


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
    lockCreated = False
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
            try:
                self.lockfile.unlink()
            except FileNotFoundError:
                # Lock file was already removed by someone else
                pass
            self.lockCreated = False
