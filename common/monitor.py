"""
monitor.py
==========
Helper functions and definitions for monitoring mercure's operations via the bookkeeper module.
"""

# Standard python includes
import asyncio
import asyncio.exceptions
from json import JSONDecodeError
import os
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError
import aiohttp
import daiquiri
import datetime
import threading

# App-specific includes
from common.types import Task, TaskProcessing
from common.event_types import *


# Create local logger instance
logger = daiquiri.getLogger("monitor")  # log_helpers.get_logger("monitor", True)
api_key: Optional[str] = None

sender_name = ""
bookkeeper_address = ""
loop: Optional[asyncio.AbstractEventLoop] = None


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


async def do_post(endpoint, kwargs, catch_errors=False) -> None:
    if api_key is None:
        return
    logger.debug(f"Posting to {endpoint}: {kwargs}")
    try:
        async with aiohttp.ClientSession(headers={"Authorization": f"Token {api_key}"},
                                         timeout=aiohttp.ClientTimeout(total=None, connect=120, sock_connect=120, sock_read=120)
                                         ) as session:
            async with session.post(bookkeeper_address + "/" + endpoint, **kwargs) as resp:
                logger.debug(f"Response from {endpoint}: {resp.status}")
                if resp.status != 200:
                    logger.warning(
                        f"Failed POST request {kwargs} to bookkeeper endpoint {endpoint}: status: {resp.status}"
                    )
    except aiohttp.client.ClientError as e:
        logger.error(f"Failed POST request to {bookkeeper_address}/{endpoint}: {e}")
        if not catch_errors:
            raise
    except asyncio.TimeoutError as e:
        logger.error(f"Failed POST request to {bookkeeper_address}/{endpoint} with timeout: {e}")
        if not catch_errors:
            raise


def post(endpoint: str, **kwargs) -> None:
    if api_key is None:
        return None

    if not bookkeeper_address:
        return None

    # create_task requires a running event loop; during boot there might not be one running yet.
    asyncio.ensure_future(do_post(endpoint, kwargs, True), loop=loop)


async def async_post(endpoint: str, **kwargs):
    if api_key is None:
        return None

    if not bookkeeper_address:
        return None

    return await do_post(
        endpoint,
        kwargs,
        True,
    )


async def get(endpoint: str, payload: Any = {}) -> Any:
    if api_key is None:
        return

    async with aiohttp.ClientSession(headers={"Authorization": f"Token {api_key}"}) as session:
        async with session.get(bookkeeper_address + "/" + endpoint, params=payload) as resp:
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
    logger.debug(f"Monitor (register-series): series_uid={tags.get('series_uid',None)}")
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

def send_processor_output(task: Task, task_processing: TaskProcessing, index:int, output: dict) -> None:
    post("store-processor-output", json=dict(task_id=task.id, task_acc=task.info.acc, task_mrn=task.info.mrn, module=task_processing.module_name, index=index, settings=task_processing.settings, output=output))
    
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


async def async_send_task_event(event: task_event, task_id: str, file_count: int, target: str, info: str):
    logger.debug(f"Monitor (task-event): event={event} task_id={task_id} info={info}")

    return await async_post("task-event", data=task_event_payload(event, task_id, file_count, target, info))


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


async def find_tasks(search_term="", study_filter="false") -> Any:
    return await get("query/find_task", {"search_term": search_term, "study_filter": study_filter})


async def task_process_logs(task_id="") -> Any:
    return await get("query/task_process_logs", {"task_id": task_id})


async def task_process_results(task_id="") -> Any:
    return await get("query/task_process_results", {"task_id": task_id})


async def get_task_info(task_id="") -> Any:
    return await get("query/get_task_info", {"task_id": task_id})
