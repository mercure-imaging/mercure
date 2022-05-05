"""
monitor.py
==========
Helper functions and definitions for monitoring mercure's operations via the bookkeeper module.
"""

# Standard python includes
import asyncio

from json import JSONDecodeError

from typing import Any, Dict, Optional
from urllib.error import HTTPError
import aiohttp
import daiquiri

# App-specific includes
from common.types import Task
from common.event_types import *


# Create local logger instance
logger = daiquiri.getLogger("monitor")  # log_helpers.get_logger("monitor", True)
api_key: Optional[str] = None

sender_name = ""
bookkeeper_address = ""
loop = None


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
        async with aiohttp.ClientSession(headers={"Authorization": f"Token {api_key}"}) as session:
            async with session.post(bookkeeper_address + "/" + endpoint, **kwargs) as resp:
                logger.debug(f"Response from {endpoint}: {resp.status}")
                if resp.status != 200:
                    logger.warning(
                        f"Failed POST request {kwargs} to bookkeeper endpoint {endpoint}: status: {resp.status}"
                    )
    except aiohttp.client_exceptions.ClientConnectorError as e:
        logger.error(f"Failed POST request to bookkeeper endpoint {endpoint}: {e}")
        if not catch_errors:
            raise


def post(endpoint: str, **kwargs) -> None:
    if api_key is None:
        return
    asyncio.ensure_future(do_post(endpoint, kwargs, True), loop=loop)


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
    bookkeeper_address = "http://" + address
    global api_key
    set_api_key()
    global loop
    loop = asyncio.get_event_loop()


def send_event(event: m_events, severity: severity = severity.INFO, description: str = "") -> None:
    """Sends information about general mercure events to the bookkeeper (e.g., during module start)."""
    logger.debug(f'Monitor (mercure-event): level {severity.value} {event}: "{description}"')

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
    if not bookkeeper_address:
        return
    logger.debug(f"Monitor (register-series): series_uid={tags.get('series_uid',None)}")
    # requests.post(bookkeeper_address + "/register-series", data=tags, timeout=1)
    post("register-series", data=tags)


def send_register_task(task: Optional[Task], task_id: str = None) -> None:
    """Registers a new task on the bookkeeper. This should be called whenever a new task has been created."""
    if not bookkeeper_address:
        return

    if task is None:
        task_dict = {"id": task_id}
    else:
        task_dict = task.dict()

    logger.debug(f"Monitor (register-task): task.id={task_dict['id']} ")

    post("register-task", json=task_dict)


def send_task_event(event: task_event, task_id, file_count, target, info) -> None:
    """Send an event related to a specific series to the bookkeeper."""
    logger.debug(f"Monitor (task-event): event={event} task_id={task_id} info={info}")

    if not bookkeeper_address:
        return

    payload = {
        "sender": sender_name,
        "event": event.value,
        "file_count": file_count,
        "target": target,
        "info": info,
        "task_id": task_id,
    }
    post("task-event", data=payload)
    # requests.post(bookkeeper_address + "/series-event", data=payload, timeout=1)


async def get_task_events(task_id="") -> Any:
    return await get("task-events", {"task_id": task_id})


async def get_series(series_uid="") -> Any:
    return await get("series", {"series_uid": series_uid})


async def get_tasks() -> Any:
    return await get("tasks")


async def get_tests() -> Any:
    return await get("tests")
