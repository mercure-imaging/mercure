"""
monitor.py
==========
Helper functions and definitions for monitoring mercure's operations via the bookkeeper module.
"""

# Standard python includes
import asyncio

from typing import Any, Dict, Optional
import logging

import aiohttp
from common.types import Task
import daiquiri
from common.helper import loop

# Create local logger instance
logger = daiquiri.getLogger("config")
api_key: Optional[str] = None

sender_name = ""
bookkeeper_address = ""


class m_events:
    """Event types for general mercure monitoring."""

    UNKNOWN = "UNKNOWN"
    BOOT = "BOOT"
    SHUTDOWN = "SHUTDOWN"
    SHUTDOWN_REQUEST = "SHUTDOWN_REQUEST"
    CONFIG_UPDATE = "CONFIG_UPDATE"
    PROCESSING = "PROCESSING"


class w_events:
    """Event types for monitoring the webgui activity."""

    UNKNOWN = "UNKNOWN"
    LOGIN = "LOGIN"
    LOGIN_FAIL = "LOGIN_FAIL"
    LOGOUT = "LOGOUT"
    USER_CREATE = "USER_CREATE"
    USER_DELETE = "USER_DELETE"
    USER_EDIT = "USER_EDIT"
    RULE_CREATE = "RULE_CREATE"
    RULE_DELETE = "RULE_DELETE"
    RULE_EDIT = "RULE_EDIT"
    TARGET_CREATE = "TARGET_CREATE"
    TARGET_DELETE = "TARGET_DELETE"
    TARGET_EDIT = "TARGET_EDIT"
    SERVICE_CONTROL = "SERVICE_CONTROL"
    CONFIG_EDIT = "CONFIG_EDIT"


class s_events:
    """Event types for monitoring everything related to one specific series."""

    UNKNOWN = "UNKNOWN"
    REGISTERED = "REGISTERED"
    ROUTE = "ROUTE"
    DISCARD = "DISCARD"
    DISPATCH = "DISPATCH"
    CLEAN = "CLEAN"
    ERROR = "ERROR"
    MOVE = "MOVE"
    SUSPEND = "SUSPEND"
    COMPLETE = "COMPLETE"


class severity:
    """Severity level associated to the mercure events."""

    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3


def set_api_key():
    global api_key
    logger.debug("getting api key")
    if api_key is None:
        from common.config import read_config

        try:
            c = read_config()
            api_key = c.bookkeeper_api_key
            logger.debug(f"API key: {api_key}")
        except (ResourceWarning, FileNotFoundError):
            logger.warning("No API key found. No bookkeeper events will be transmitted.")
            return


def post(endpoint: str, **kwargs) -> None:
    if api_key is None:
        return

    async def do_post(endpoint, kwargs) -> None:
        logger.debug(f"Posting to {endpoint}: {kwargs}")
        try:
            async with aiohttp.ClientSession(headers={"Authorization": f"Token {api_key}"}) as session:
                async with session.post(bookkeeper_address + "/" + endpoint, **kwargs) as resp:
                    logger.debug(f"Response from {endpoint}: {resp.status}")
                    if resp.status != 200:
                        logger.warning(f"Failed POST request to bookkeeper endpoint {endpoint}: status: {resp.status}")
        except aiohttp.client_exceptions.ClientConnectorError as e:
            logger.error(f"Failed POST request to bookkeeper endpoint {endpoint}: {e}")

    asyncio.ensure_future(do_post(endpoint, kwargs), loop=loop)


async def get(endpoint: str, payload: Any) -> Any:
    if api_key is None:
        return

    async with aiohttp.ClientSession(headers={"Authorization": f"Token {api_key}"}) as session:
        async with session.get(bookkeeper_address + "/" + endpoint, params=payload) as resp:
            if resp.status != 200:
                logger.error(f"Failed GET request to bookkeeper endpoint {endpoint}: status: {resp.status}")
                return {}
            return await resp.json()


def configure(module, instance, address) -> None:
    """Configures the connection to the bookkeeper module. If not called, events
    will not be transmitted to the bookkeeper."""
    global sender_name
    global bookkeeper_address
    sender_name = module + "." + instance
    bookkeeper_address = "http://" + address
    global api_key
    set_api_key()


def send_event(event, severity=severity.INFO, description: str = "") -> None:
    """Sends information about general mercure events to the bookkeeper (e.g., during module start)."""
    if not bookkeeper_address:
        return
    logger.debug(f"Monitor (mercure-event): level {severity} {event}: {description}")
    payload = {
        "sender": sender_name,
        "event": event,
        "severity": severity,
        "description": description,
    }
    post("mercure-event", data=payload)
    # requests.post(bookkeeper_address + "/mercure-event", data=payload, timeout=1)


def send_webgui_event(event, user, description="") -> None:
    """Sends information about an event on the webgui to the bookkeeper."""
    if not bookkeeper_address:
        return
    payload = {
        "sender": sender_name,
        "event": event,
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


def send_register_task(task: Task) -> None:
    """Registers a received series on the bookkeeper. This should be called when a series has been
    fully received and the DICOM tags have been parsed."""
    if not bookkeeper_address:
        return
    logger.debug(f"Monitor (register-task): task.id={task.id} ")
    post("register-task", json=task.dict())
    # requests.post(bookkeeper_address + "/register-task", data=json.dumps(task.dict()), timeout=1)


def send_task_event(event, task_id, file_count, target, info) -> None:
    """Send an event related to a specific series to the bookkeeper."""
    if not bookkeeper_address:
        return

    logger.debug(f"Monitor (task-event): event={event} task_id={task_id} info={info}")
    payload = {
        "sender": sender_name,
        "event": event,
        "file_count": file_count,
        "target": target,
        "info": info,
        "task_id": task_id,
    }
    post("task-event", data=payload)
    # requests.post(bookkeeper_address + "/series-event", data=payload, timeout=1)


async def get_task_events(task_id="") -> Any:
    """Send an event related to a specific series to the bookkeeper."""
    return await get("task-events", {"task_id": task_id})


async def get_series(series_uid="") -> Any:
    """Send an event related to a specific series to the bookkeeper."""
    return await get("series", {"series_uid": series_uid})


async def get_tasks(series_uid="") -> Any:
    """Send an event related to a specific series to the bookkeeper."""
    return await get("tasks", {"series_uid": series_uid})
