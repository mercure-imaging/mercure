"""
notification.py
===============
Helper functions for triggering webhook calls.
"""

# Standard python includes
from pathlib import Path
import json
import daiquiri
import json
import requests
import traceback

# App-specific includes
from common.constants import (
    mercure_events,
)


# Create local logger instance
logger = daiquiri.getLogger("notification")


def send_webhook(url, payload, event) -> None:
    if (not url) or (not payload):
        return

    # Replace macros in payload
    payload_parsed = payload

    if event == mercure_events.RECEPTION:
        payload_parsed=payload_parsed.replace("@event@","RECEIVED")
    if event == mercure_events.COMPLETION:
        payload_parsed=payload_parsed.replace("@event@","COMPLETED")
    if event == mercure_events.ERROR:
        payload_parsed=payload_parsed.replace("@event@","ERROR")

    try:         
        payload_data = json.loads("{" + payload_parsed + "}")
        response = requests.post(
            url, data=json.dumps(payload_data), headers={"Content-type": "application/json"}
        )
        if (response.status_code != 200) and (response.status_code != 204):
            logger.error(f"ERROR: Webhook notification failed (status code {response.status_code})")
            logger.error(f"ERROR: {response.text}")
    except:
        logger.error(f"ERROR: Webhook notification failed")
        logger.error(traceback.format_exc())
        return
