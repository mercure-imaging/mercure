import requests
import daiquiri
import logging

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("config")

sender_name       =""
bookkeeper_address=""


class h_events:
    UKNOWN           = "UNKNOWN"
    BOOT             = "BOOT"
    SHUTDOWN         = "SHUTDOWN"
    SHUTDOWN_REQUEST = "SHUTDOWN_REQUEST"
    CONFIG_UPDATE    = "CONFIG_UPDATE"


class w_events:
    UKNOWN           = "UNKNOWN"
    LOGIN            = "LOGIN"
    LOGIN_FAIL       = "LOGIN_FAIL"
    LOGOUT           = "LOGOUT"
    USER_CREATE      = "USER_CREATE"
    USER_DELETE      = "USER_DELETE"
    USER_EDIT        = "USER_EDIT"
    RULE_CREATE      = "RULE_CREATE"
    RULE_DELETE      = "RULE_DELETE"
    RULE_EDIT        = "RULE_EDIT"
    TARGET_CREATE    = "TARGET_CREATE"
    TARGET_DELETE    = "TARGET_DELETE"
    TARGET_EDIT      = "TARGET_EDIT"
    SERVICE_CONTROL  = "SERVICE_CONTROL"


class s_events:
    UKNOWN           = "UNKNOWN"
    ROUTE            = "ROUTE"
    DISCARD          = "DISCARD"
    DISPATCH         = "DISPATCH"
    CLEAN            = "CLEAN"
    ERROR            = "ERROR"


class severity:
    INFO             = 0
    WARNING          = 1
    ERROR            = 2
    CRITICAL         = 3


def configure(module,instance,address):
    global sender_name
    global bookkeeper_address
    sender_name=module+"."+instance
    bookkeeper_address='http://'+address


def send_event(event, severity = severity.INFO, description = ""):
    if not bookkeeper_address:
        return
    try:
        payload = {'sender': sender_name, 'event': event, 'severity': severity, 'description': description }        
        requests.post(bookkeeper_address+"/hermes-event", data=payload, timeout=1)
    except requests.exceptions.RequestException as e:
        logger.warning("Failed request to bookkeeper")
        logger.warning(e)


def send_webgui_event(event, user, description = ""):
    if not bookkeeper_address:
        return
    try:
        payload = {'sender': sender_name, 'event': event, 'user': user, 'description': description }
        requests.post(bookkeeper_address+"/webgui-event", data=payload, timeout=1)
    except requests.exceptions.RequestException as e:
        logger.warning("Failed request to bookkeeper")
        logger.warning(e)


def send_register_series(tags):
    if not bookkeeper_address:
        return
    try:
        requests.post(bookkeeper_address+"/register-series", data=tags, timeout=1)
    except requests.exceptions.RequestException as e:
        logger.warning("Failed request to bookkeeper")
        logger.warning(e)


def send_series_event(event, series_uid, file_count, target, info):
    if not bookkeeper_address:
        return
    try:
        payload = {'sender': sender_name, 'event': event, 'series_uid': series_uid,
                   'file_count': file_count, 'target': target, 'info': info }
        requests.post(bookkeeper_address+"/series-event", data=payload, timeout=1)
    except requests.exceptions.RequestException as e:
        logger.warning("Failed request to bookkeeper")
        logger.warning(e)
