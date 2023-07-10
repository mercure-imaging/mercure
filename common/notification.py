"""
notification.py
===============
Helper functions for triggering webhook calls.
"""

# Standard python includes
import json
from typing import Any
import aiohttp
import daiquiri
import json
import asyncio
import traceback
from .helper import loop
import common.config as config

# App-specific includes
from common.constants import (
    mercure_events,
)


# Create local logger instance
logger = config.get_logger()


def post(url: str, payload: Any) -> None:
    async def do_post(url, payload) -> None:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status not in (200, 204):
                        logger.warning(f"Webhook notification failed {url}, status: {resp.status}")
                    # logger.warning(f"{await resp.text()}")
            except Exception as e:
                logger.warning(f"Webhook notification failed {url}, exception: {e}")
                logger.warning(traceback.format_exc())

    asyncio.ensure_future(do_post(url, payload), loop=loop)

def parse_payload(payload: str, event: mercure_events, rule_name: str, task_id: str) -> str:
    payload_parsed = payload
    payload_parsed = payload_parsed.replace("@rule@", rule_name)
    payload_parsed = payload_parsed.replace("@task_id@", task_id)
    payload_parsed = payload_parsed.replace("@event@", event.name)

    return payload_parsed

def send_webhook(url:str, payload: str, event: mercure_events, rule_name: str, task_id: str ="") -> None:
    if (not url):
        return

    # Replace macros in payload
    payload_parsed = parse_payload(payload,event, rule_name, task_id)
    try:
        payload_data = json.loads("{" + payload_parsed + "}")
        post(url, payload_data)
        # response = requests.post(
        #     url, data=json.dumps(payload_data), headers={"Content-type": "application/json"}
        # )
        # if (response.status_code != 200) and (response.status_code != 204):
        #     logger.error(f"ERROR: Webhook notification failed (status code {response.status_code})")
        #     logger.error(f"ERROR: {response.text}")
    except:
        logger.error(f"ERROR: Webhook notification failed")
        logger.error(traceback.format_exc())
        return

import smtplib
from email.message import EmailMessage

def send_email(address: str, payload: str, event: mercure_events, rule_name: str, task_id: str="") -> None:
    if not address:
        return
    payload_parsed = parse_payload(payload,event, rule_name, task_id)
    subject = f"Rule {rule_name} {event}"
    try: 
        send_email_helper(address, subject, payload_parsed)
    except:
        logger.exception(f"ERROR: Email notification failed")


def send_email_helper(to:str, subject:str, content:str) -> None:
    # Create a text/plain message
    msg = EmailMessage()
    msg['Subject'] = f'[Mercure] {subject}'
    msg['From'] = "test@example.com"
    msg['To'] = to
    msg.set_content(content)

    # Send the message via our own SMTP server.
    s = smtplib.SMTP('localhost')
    try: 
        s.send_message(msg)
    finally:
        s.quit()