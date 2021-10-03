"""
notification.py
===============
Helper functions for triggering webhook calls.
"""

# Standard python includes
import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri
import json
import requests
import traceback

# App-specific includes
import common.config as config
import common.monitor as monitor
import common.helper as helper
from common.constants import (
    mercure_defs,
    mercure_names,
    mercure_sections,
    mercure_rule,
    mercure_config,
    mercure_options,
    mercure_events,
)

# Create local logger instance
logger = daiquiri.getLogger("notification")


def send_webhook(url, payload, event) -> None:
    if not url:
        return

    # TODO: Replace macros in payload

    if event == mercure_events.RECEPTION:
        pass
    if event == mercure_events.COMPLETION:
        pass
    if event == mercure_events.ERROR:
        pass

    # TODO: Incomplete implementation

    try:         
        payload_data = json.loads("{" + payload + "}")
        response = requests.post(
            url, data=json.dumps(payload_data), headers={"Content-type": "application/json"}
        )
        if response.status_code != 200:
            logger.error(f"ERROR: Webhook notification failed (status code {response.status_code})")
            logger.error(f"ERROR: {response.text}")
    except:
        logger.error(f"ERROR: Webhook notification failed")
        logger.error(traceback.format_exc())
        return
