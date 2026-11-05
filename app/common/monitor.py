"""
monitor.py
==========
Helper functions and definitions for monitoring mercure's operations via the bookkeeper module.
"""

# Standard python includes
import asyncio
import asyncio.exceptions
import contextlib
import datetime
import os
import time
from json import JSONDecodeError
from typing import Any, Dict, Optional, Tuple

import aiohttp
import daiquiri
from common.event_types import m_events, severity, task_event, w_events
# App-specific includes
from common.types import Task, TaskProcessing

# Create local logger instance
logger = daiquiri.getLogger("monitor")  # log_helpers.get_logger("monitor", True)
api_key: Optional[str] = None

sender_name = ""
bookkeeper_address = ""
loop: Optional[asyncio.AbstractEventLoop] = None

# ---------------------------------------------------------------------------------------------
# Reporting pipeline
# ---------------------------------------------------------------------------------------------
#
# post() hands events to one bounded queue per process, drained by a single consumer task:
#
# * submitting is a put_nowait, so no service path ever waits for the bookkeeper;
# * overflow is dropped and logged (rate-limited) - missing telemetry is survivable, a stalled study is not;
# * delivery is serial, so events from one process arrive in the order they were produced (ordering
#   across processes is not provided);
# * reports use their own small connection pool with a configured deadline, so a backlog cannot starve
#   the queue UI's reads (get()), which keep aiohttp's default timeouts.
#
# The pipeline is bound to the process's event loop and created on first use; shutdown() drains it
# within a deadline and closes the pools.

#: Overall deadline for one report, in seconds.
DEFAULT_TIMEOUT = 15.0
#: Events that may wait in the queue before new ones are dropped.
DEFAULT_QUEUE_SIZE = 1000
#: Connections per pool. Delivery is serial, so the reporting pool stays small.
REPORTING_POOL_LIMIT = 2
QUERY_POOL_LIMIT = 10
#: Log one line per this many drops, so an outage does not flood the log.
DROP_LOG_EVERY = 100
#: Name of the consumer task, so the shutdown drain can tell it apart from application work.
CONSUMER_TASK_NAME = "bookkeeper-reporting"


class _Pipeline:
    """The event queue, its consumer, and the connection pools."""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop], queue_size: int) -> None:
        self.loop = loop
        self.queue: "asyncio.Queue[Tuple[str, Dict[str, Any]]]" = asyncio.Queue(maxsize=queue_size)
        self.consumer: Optional["asyncio.Task[None]"] = None
        self.sessions: Dict[bool, aiohttp.ClientSession] = {}
        self.dropped = 0
        self.closed = False

    def submit(self, endpoint: str, kwargs: Dict[str, Any]) -> None:
        """Queue one event. Never performs I/O and never blocks."""
        if self.closed:
            self._drop(f"Dropping {endpoint}: bookkeeper reporting has been shut down")
            return
        try:
            self.queue.put_nowait((endpoint, kwargs))
        except asyncio.QueueFull:
            self._drop(f"Bookkeeper reporting backlog is full ({self.queue.maxsize} events); dropping {endpoint}. "
                       "The bookkeeper is not keeping up or is unreachable.")
            return
        self._ensure_consumer()

    def _drop(self, message: str) -> None:
        self.dropped += 1
        if self.dropped % DROP_LOG_EVERY == 1:
            logger.error(f"{message} ({self.dropped} dropped so far)")

    def _ensure_consumer(self) -> None:
        if self.loop is not None and (self.consumer is None or self.consumer.done()):
            self.consumer = self.loop.create_task(self._run(), name=CONSUMER_TASK_NAME)

    async def _run(self) -> None:
        while True:
            endpoint, kwargs = await self.queue.get()
            try:
                await do_post(endpoint, kwargs, catch_errors=True, reporting=True)
            except Exception as e:  # one bad event must not stop the ones queued behind it
                logger.error(f"Failed to report {endpoint} to the bookkeeper: {e}")
            finally:
                self.queue.task_done()

    def session(self, reporting: bool = False) -> aiohttp.ClientSession:
        """The shared pool for reports (``reporting=True``) or for interactive requests."""
        http = self.sessions.get(reporting)
        if http is None or http.closed:
            limit = REPORTING_POOL_LIMIT if reporting else QUERY_POOL_LIMIT
            options: Dict[str, Any] = {"timeout": aiohttp.ClientTimeout(total=_timeout())} if reporting else {}
            http = aiohttp.ClientSession(
                headers={"Authorization": f"Token {api_key}"} if api_key else {},
                connector=aiohttp.TCPConnector(limit=limit, limit_per_host=limit),
                **options,
            )
            self.sessions[reporting] = http
        return http

    async def aclose(self, timeout: float) -> bool:
        """Drain for up to ``timeout`` seconds, then stop the consumer and close the pools."""
        self.closed = True  # nothing submitted from now on could be delivered
        self._ensure_consumer()
        try:
            await asyncio.wait_for(self.queue.join(), timeout)
            drained = True
        except asyncio.TimeoutError:
            drained = False
            logger.error(f"Bookkeeper reporting did not drain within {timeout}s; "
                         f"{self.queue.qsize()} queued event(s) are dropped")

        if self.consumer is not None:
            self.consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.consumer
        for http in self.sessions.values():
            await http.close()
        self.sessions.clear()
        return drained


_pipeline: Optional[_Pipeline] = None


def _config_number(name: str, default: float) -> float:
    """A positive numeric setting from the mercure config; unusable values fall back to ``default``."""
    try:
        from common import config as app_config  # imported here: common.config imports this module

        value = getattr(app_config.mercure, name, None)
        if value is None:
            return float(default)
        number = float(value)
    except Exception as e:
        logger.error(f"Cannot read {name} ({e}); using {default}")
        return float(default)
    if number <= 0:
        logger.error(f"{name} must be greater than zero, got {value}; using {default}")
        return float(default)
    return number


def _timeout() -> float:
    return _config_number("bookkeeper_timeout", DEFAULT_TIMEOUT)


def _get_pipeline() -> _Pipeline:
    """This process's pipeline, bound to the running loop, or the one configure() captured."""
    global _pipeline
    try:
        live_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        live_loop = loop
    if _pipeline is None:
        _pipeline = _Pipeline(live_loop, int(_config_number("bookkeeper_queue_size", DEFAULT_QUEUE_SIZE)))
    elif _pipeline.loop is None:
        _pipeline.loop = live_loop
    return _pipeline


async def shutdown(timeout: float = 10.0) -> bool:
    """Drain reporting within ``timeout``, then stop the consumer and close the pools.

    Bounded, so a stopping service stays inside its supervisor's stop timeout. Events submitted
    afterwards are dropped. Returns True when everything queued was delivered in time.
    """
    if _pipeline is None or _pipeline.closed:
        return True
    return await _get_pipeline().aclose(timeout)  # binds a pipeline created before the loop started


class MonitorHTTPError(Exception):
    """Exception raised when a HTTP error occurs."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        logger.debug("HTTP error: %s", message)


def set_api_key() -> None:
    global api_key
    if api_key is None:
        from common.config import read_config

        try:
            c = read_config()
            api_key = c.bookkeeper_api_key
        except (ResourceWarning, FileNotFoundError):
            logger.warning("No API key found. No bookkeeper events will be transmitted.")
            return


async def do_post(endpoint, kwargs, catch_errors=False, reporting: bool = False) -> bool:
    """Send one request to the bookkeeper. True only when it answered with 200.

    ``reporting`` selects the reporting pool (used by the queue consumer); direct callers such as the
    webinterface use the interactive pool.
    """
    if api_key is None:
        return False
    logger.debug(f"Posting to {endpoint}: {kwargs}")
    try:
        async with _get_pipeline().session(reporting).post(bookkeeper_address + "/" + endpoint, **kwargs) as resp:
            logger.debug(f"Response from {endpoint}: {resp.status}")
            if resp.status != 200:
                logger.warning(
                    f"Failed POST request {kwargs} to bookkeeper endpoint {endpoint}: status: {resp.status}"
                )
                return False
            return True
    except aiohttp.client.ClientError as e:
        logger.error(f"Failed POST request to {bookkeeper_address}/{endpoint}: {e}")
        if not catch_errors:
            raise
        return False
    except asyncio.TimeoutError as e:
        logger.error(f"Failed POST request to {bookkeeper_address}/{endpoint} with timeout: {e}")
        if not catch_errors:
            raise
        return False


def post(endpoint: str, **kwargs) -> None:
    """Queue an event for the bookkeeper. Never performs I/O and never blocks."""
    if api_key is None or not bookkeeper_address:
        return
    _get_pipeline().submit(endpoint, kwargs)


async def get(endpoint: str, payload: Any = {}) -> Any:
    if api_key is None:
        return

    # The interactive pool, with aiohttp's default timeouts: reads must not line up behind reports.
    async with _get_pipeline().session().get(bookkeeper_address + "/" + endpoint, params=payload) as resp:
        if resp.status != 200:
            logger.error(f"Failed GET request to bookkeeper endpoint {endpoint}: status: {resp.status}")
            if resp.content_type == "application/json":
                try:
                    err_json = await resp.json()
                except JSONDecodeError:
                    raise MonitorHTTPError(resp.status, await resp.text())
            else:
                raise MonitorHTTPError(resp.status, await resp.text())
            try:
                raise MonitorHTTPError(resp.status, str(err_json["error"]))
            except KeyError:
                raise MonitorHTTPError(resp.status, "Unknown error")

        return await resp.json()


def configure(module, instance, address) -> None:
    """Configures the connection to the bookkeeper module. If not called, events
    will not be transmitted to the bookkeeper."""
    global sender_name
    sender_name = module + "." + instance
    global bookkeeper_address
    if addr := os.getenv("MERCURE_BOOKKEEPER_PATH"):
        bookkeeper_address = "http://" + addr
    else:
        bookkeeper_address = "http://" + address
    global api_key
    set_api_key()
    global loop
    loop = asyncio.get_event_loop()


def send_event(event: m_events, severity: severity = severity.INFO, description: str = "") -> None:
    """Sends information about general mercure events to the bookkeeper (e.g., during module start)."""
    logger.debug(
        f'Monitor (mercure-event): level {severity.value} {event}: "{description}"'
    )

    if not bookkeeper_address:
        return
    payload = {
        "sender": sender_name,
        "event": event.value,
        "severity": severity.value,
        "description": description,
    }
    post("mercure-event", data=payload)
    # requests.post(bookkeeper_address + "/mercure-event", data=payload, timeout=1)


def send_webgui_event(event: w_events, user: str, description="") -> None:
    """Sends information about an event on the webgui to the bookkeeper."""
    if not bookkeeper_address:
        return
    payload = {
        "sender": sender_name,
        "event": event.value,
        "user": user,
        "description": description,
    }
    post("webgui-event", data=payload)
    # requests.post(bookkeeper_address + "/webgui-event", data=payload, timeout=1)


def send_register_series(tags: Dict[str, str]) -> None:
    """Registers a received series on the bookkeeper. This should be called when a series has been
    fully received and the DICOM tags have been parsed."""
    logger.debug(f"Monitor (register-series): series_uid={tags.get('series_uid', None)}")
    # requests.post(bookkeeper_address + "/register-series", data=tags, timeout=1)
    post("register-series", data=tags)


def send_register_task(task_id: str, series_uid: str, parent_id: Optional[str] = None) -> None:
    """Registers a new task on the bookkeeper. This should be called whenever a new task has been created."""
    post("register-task", json={"id": task_id, "series_uid": series_uid, "parent_id": parent_id})


def send_update_task(task: Task) -> None:
    """Registers a new task on the bookkeeper. This should be called whenever a new task has been created."""
    task_dict = task.dict()

    logger.debug(f"Monitor (update-task): task.id={task_dict['id']} ")

    post("update-task", json=task_dict)


def send_update_task_tags(id, info_dict) -> None:
    """ 

    """
    post("update-task", json={"id": id, "tags": info_dict})


def send_processor_output(task: Task, task_processing: TaskProcessing, index: int, output: dict) -> None:
    post("store-processor-output",
         json=dict(task_id=task.id, task_acc=task.info.acc, task_mrn=task.info.mrn,
                   module=task_processing.module_name, index=index,
                   settings=task_processing.settings, output=output))


def task_event_payload(event: task_event, task_id: str, file_count: int, target, info):
    return {
        "sender": sender_name,
        "event": event.value,
        "file_count": file_count,
        "target": target,
        "info": info,
        "task_id": task_id,
        "timestamp": time.monotonic(),
        "time": datetime.datetime.now(),
    }


def send_task_event(event: task_event, task_id: str, file_count: int, target: str, info: str) -> None:
    """Send an event related to a specific series to the bookkeeper."""
    logger.debug(f"Monitor (task-event): event={event} task_id={task_id} info={info}")

    post("task-event", data=task_event_payload(event, task_id, file_count, target, info))


def send_process_logs(task_id: str, module_name: str, logs: str) -> None:
    logger.debug(f"Monitor (processor-logs): task_id={task_id}")

    payload = {
        "sender": sender_name,
        "task_id": task_id,
        "module_name": module_name,
        "time": datetime.datetime.now(),
        "logs": logs,
    }
    post("processor-logs", data=payload)


async def get_task_events(task_id="") -> Any:
    return await get("query/task-events", {"task_id": task_id})


async def get_series(series_uid="") -> Any:
    return await get("query/series", {"series_uid": series_uid})


async def get_tasks() -> Any:
    return await get("query/tasks")


async def get_tests() -> Any:
    return await get("query/tests")


async def find_tasks(request) -> Any:
    return await get("query/find_task", {k: v for k, v in request.query_params.items()})


async def task_process_logs(task_id="") -> Any:
    return await get("query/task_process_logs", {"task_id": task_id})


async def task_process_results(task_id="") -> Any:
    return await get("query/task_process_results", {"task_id": task_id})


async def get_task_info(task_id="") -> Any:
    return await get("query/get_task_info", {"task_id": task_id})
