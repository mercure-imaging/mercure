"""
notification.py
===============
Helper functions for triggering webhook calls.
"""

# Standard python includes
import json
from typing import Any, Optional
import aiohttp
import daiquiri
import json
import asyncio
import traceback

import jinja2.utils

from common import monitor
from common.types import Rule, Task
from .helper import loop
import common.config as config
from jinja2 import Template

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
                        logger.warning(payload)
                    # logger.warning(f"{await resp.text()}")
            except Exception as e:
                logger.warning(f"Webhook notification failed {url}, exception: {e}")
                logger.warning(traceback.format_exc())

    asyncio.ensure_future(do_post(url, payload), loop=loop)


def parse_payload(payload: str, event: mercure_events, rule_name: str, task_id: str, details: str ="", context: dict={}) -> str:
    payload_parsed = payload
    payload_parsed = payload_parsed.replace("@rule@", rule_name)
    payload_parsed = payload_parsed.replace("@task_id@", task_id)
    payload_parsed = payload_parsed.replace("@event@", event.name)
    context = {**dict(rule=rule_name, task_id=task_id, event=event.name, details=details),**context}
    
    return Template(payload_parsed).render(context)
    

def send_webhook(url:str, payload: str) -> None:
    if not url:
        return

    # Replace macros in payload
    try:
        payload_data = json.loads("{" + payload + "}")
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

def send_email(address: str, payload: str, event: mercure_events, rule_name: str) -> None:
    if not address:
        return
    subject = f"Rule {rule_name}: {event.name}"
    try: 
        send_email_helper(address, subject, payload)
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


def trigger_notification_for_rule(rule_name: str, task_id: str, event: mercure_events, details: str="", task: Optional[Task] = None):
    current_rule = config.mercure.rules.get(rule_name)
    # Check if the rule is available
    if not current_rule or not isinstance(current_rule, Rule):
        logger.error(f"Rule {rule_name} does not exist in mercure configuration", task_id)  # handle_error
        return False


    do_send = False
    # Now fire the webhook if configured
    if event == mercure_events.RECEPTION and current_rule.notification_trigger_reception == True:
        do_send = True
    elif event == mercure_events.COMPLETION and current_rule.notification_trigger_completion == True:
        do_send = True
    elif event == mercure_events.ERROR and current_rule.notification_trigger_error == True:
        do_send = True
    
    if not do_send:
        return

    webhook_url = current_rule.get("notification_webhook")
    if webhook_url:
        body = current_rule.get("notification_payload_body", "")
        context = dict(body=jinja2.utils.htmlsafe_json_dumps(parse_payload(body,event, rule_name, task_id, details))[1:-1])

        webhook_payload = parse_payload(current_rule.get("notification_payload", ""),event, rule_name, task_id, details, context)
        logger.warning(webhook_payload)
        send_webhook(
            webhook_url,
            webhook_payload
        )
        monitor.send_task_event(
            monitor.task_event.NOTIFICATION,
            task_id,
            0,
            webhook_url,
            "Announced " + event.name,
        )

    email_address = current_rule.get("notification_email")
    if email_address:
        if task:
            context = dict(acc=task.info.acc, mrn=task.info.mrn, patient_name=task.info.patient_name)
        else:
            context = {}
        email_payload = parse_payload(current_rule.get("notification_email_body", ""),event, rule_name, task_id, details, context)
        send_email(
            email_address,
            email_payload,
            event,
            rule_name,
        )
        monitor.send_task_event(
            monitor.task_event.NOTIFICATION,
            task_id,
            0,
            email_address,
            "Announced " + event.name,
        )
    return True