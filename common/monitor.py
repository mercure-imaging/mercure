import requests

sender_name=""
bookkeeper_address=""

class h_events:
    UKNOWN=0
    BOOT=1
    SHUTDOWN=2
    SHUTDOWN_REQUEST=3
    CONFIG_UPDATE=4


class severity:
    INFO=0
    WARNING=1
    ERROR=2
    CRITICAL=3


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
        requests.post(bookkeeper_address+"/hermes-event", params=payload)
    except:
        pass
