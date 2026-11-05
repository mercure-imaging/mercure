"""
helper.py
=========
Various internal helper functions for mercure.
"""
# Standard python includes
import asyncio
import inspect
import os
import re
import threading
from datetime import datetime
from datetime import time as _time
from pathlib import Path
from typing import Callable, Optional, Tuple

import common.influxdb
import common.monitor as monitor
import daiquiri
import dateutil
import graphyte

# Not log_helpers.get_logger(): log_helpers imports this module and calls get_runner() while setting up,
# and its handler reports warnings to the bookkeeper, which is the wrong place during shutdown.
logger = daiquiri.getLogger("helper")

# Global variable to broadcast when the process should terminate
terminate = False

loop = asyncio.get_event_loop()


def validate_folders(config) -> Tuple[bool, str]:
    for folder in (config.incoming_folder, config.studies_folder, config.outgoing_folder,
                   config.success_folder, config.error_folder, config.discard_folder,
                   config.processing_folder, config.jobs_folder):
        if not Path(folder).is_dir():
            try:
                Path(folder).mkdir(parents=False)
                print(f"Created directory: {folder}")
            except Exception:
                return False, f"Folder {folder} does not exist."

        if not os.access(folder, os.R_OK | os.W_OK):
            return False, f"No read/write access to {folder}"
    return True, ""


def localize_log_timestamps(logstring: str, config) -> str:
    if config.mercure.local_time == "UTC":
        return logstring
    try:
        local_tz = dateutil.tz.gettz(config.mercure.local_time)  # type: ignore
    except Exception:
        return logstring

    timestamp_pattern = re.compile(r'^(\S+)(.*?)$', re.MULTILINE)

    def replace_timestamp(match):
        timestamp, rest_of_line = match.groups()
        try:
            parsed_dt = dateutil.parser.isoparse(timestamp)  # type: ignore
            dt_localtime: datetime = parsed_dt.astimezone(local_tz)
            localized_timestamp = dt_localtime.isoformat(timespec='seconds')
            return f"{localized_timestamp}{rest_of_line}"
        except Exception:
            return match.group(0)  # Return the original line if parsing fails

    return timestamp_pattern.sub(replace_timestamp, logstring)


def get_now_str() -> str:
    """Returns the current time as string with mercure-wide formatting"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_runner() -> str:
    """Returns the name of the mechanism that is used for running mercure
       in the current installation (systemd, docker, nomad)."""
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
    if graphyte.default_sender is None:
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
    except Exception:
        send_to_graphite(*args, **kwargs)
        send_to_influxdb(*args, **kwargs)


def _is_offpeak(offpeak_start: str, offpeak_end: str, current_time: _time) -> bool:
    """Check if the provided time is within the offpeak time range."""
    try:
        start_time = datetime.strptime(offpeak_start, "%H:%M").time()
        end_time = datetime.strptime(offpeak_end, "%H:%M").time()
    except Exception:
        logger.error(f"Unable to parse offpeak time: {offpeak_start}, {offpeak_end}")
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
        """Starts the timer for triggering the callback after the defined interval."""
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


#: Shutdown deadlines, in seconds. Their sum stays inside the supervisors' stop timeout
#: (TimeoutStopSec=120 in the unit files, stop_grace_period: 2m in docker-compose.yml).
SHUTDOWN_TASK_TIMEOUT = 60.0
SHUTDOWN_MONITOR_TIMEOUT = 10.0


def drain_pending_tasks(loop: asyncio.AbstractEventLoop,
                        monitor_timeout: float = SHUTDOWN_MONITOR_TIMEOUT,
                        task_timeout: float = SHUTDOWN_TASK_TIMEOUT) -> None:
    """Bounded shutdown for a service whose event loop has stopped.

    Waits up to ``task_timeout`` for outstanding tasks and cancels the rest, then drains bookkeeper
    reporting (last, so work finishing during shutdown can still report), then closes metrics - after the
    loop, because the InfluxDB close blocks (for at most its max_close_wait).
    """
    if loop.is_running():
        raise RuntimeError("drain_pending_tasks() must be called after the event loop has stopped")

    # Snapshot the outstanding work *before* the drain starts. Collecting it from inside _drain() also
    # picks up the drain's own wrapper: on Python < 3.12, asyncio.wait_for() runs _drain() in a separate
    # task, so current_task() is not the task run_until_complete() is waiting on. The drain then waited
    # for itself, timed out and cancelled itself (CancelledError).
    remaining = {task for task in asyncio.all_tasks(loop)
                 if not task.done() and task.get_name() != monitor.CONSUMER_TASK_NAME}

    async def _drain() -> None:
        if remaining:
            _, pending = await asyncio.wait(remaining, timeout=task_timeout)
            if pending:
                logger.warning(f"Cancelling {len(pending)} task(s) that did not finish within {task_timeout}s")
                for task in pending:
                    task.cancel()
                await asyncio.wait(pending, timeout=2)
        await monitor.shutdown(monitor_timeout)

    try:
        # Backstop for the steps that are not strictly bounded (cancellation, closing the pools).
        loop.run_until_complete(asyncio.wait_for(_drain(), task_timeout + monitor_timeout + 5))
    except Exception as e:  # a shutdown that cannot drain must still exit
        logger.error(f"Shutdown drain did not complete cleanly: {e}")


class FileLock:
    """A lock file that marks a folder as "being worked on".

    The lock is released only by an explicit :meth:`free` (or by leaving a ``with`` block). There is
    deliberately no destructor: a lock that disappears when the owning frame is garbage collected
    unlocks half-written folders on any unexpected exception, which hands them to the next service.
    Use it as a context manager. By default the lock is released when the block is left, also
    on an exception. Pass ``keep_on_error=True`` for a lock that guards a folder being *filled*:
    if the block raises, the lock stays so that a half-written folder is never handed over.
    """
    lockCreated = False

    def __init__(self, path_for_lockfile: Path, keep_on_error: bool = False):
        self.lockfile = path_for_lockfile
        self.keep_on_error = keep_on_error
        self.lockfile.touch(exist_ok=False)
        self.lockCreated = True

    def __enter__(self) -> "FileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None and self.keep_on_error:
            return
        self.free()

    def free(self) -> None:
        if self.lockCreated:
            try:
                self.lockfile.unlink()
            except FileNotFoundError:
                # Lock file was already removed by someone else
                pass
            self.lockCreated = False
