"""
monitor.py
==========
Helper functions and definitions for monitoring mercure's operations via the bookkeeper module.
"""

# Standard python includes
from typing import Dict
import requests
import daiquiri
import logging

# Create local logger instance
logger = daiquiri.getLogger("config")

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


class severity:
    """Severity level associated to the mercure events."""

    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3


def configure(module, instance, address) -> None:
    """Configures the connection to the bookkeeper module. If not called, events
    will not be transmitted to the bookkeeper."""
    global sender_name
    global bookkeeper_address
    sender_name = module + "." + instance
    bookkeeper_address = "http://" + address


def send_event(event, severity=severity.INFO, description: str = "") -> None:
    """Sends information about general mercure events to the bookkeeper (e.g., during module start)."""
    if not bookkeeper_address:
        return
    try:
        payload = {
            "sender": sender_name,
            "event": event,
            "severity": severity,
            "description": description,
        }
        requests.post(bookkeeper_address + "/mercure-event", data=payload, timeout=1)
    except requests.exceptions.RequestException:
        logger.error("Failed request to bookkeeper")


def send_webgui_event(event, user, description="") -> None:
    """Sends information about an event on the webgui to the bookkeeper."""
    if not bookkeeper_address:
        return
    try:
        payload = {
            "sender": sender_name,
            "event": event,
            "user": user,
            "description": description,
        }
        requests.post(bookkeeper_address + "/webgui-event", data=payload, timeout=1)
    except requests.exceptions.RequestException:
        logger.error("Failed request to bookkeeper")


def send_register_series(tags: Dict[str, str]) -> None:
    """Registers a received series on the bookkeeper. This should be called when a series has been
    fully received and the DICOM tags have been parsed."""
    if not bookkeeper_address:
        return
    try:
        requests.post(bookkeeper_address + "/register-series", data=tags, timeout=1)
    except requests.exceptions.RequestException:
        logger.error("Failed request to bookkeeper")


def send_series_event(event, series_uid, file_count, target, info) -> None:
    """Send an event related to a specific series to the bookkeeper."""
    if not bookkeeper_address:
        return
    try:
        payload = {
            "sender": sender_name,
            "event": event,
            "series_uid": series_uid,
            "file_count": file_count,
            "target": target,
            "info": info,
        }
        requests.post(bookkeeper_address + "/series-event", data=payload, timeout=1)
    except requests.exceptions.RequestException:
        logger.error("Failed request to bookkeeper")
