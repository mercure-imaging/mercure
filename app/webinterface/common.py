"""
common.py
=========
Helper functions for the graphical user interface of mercure.
"""

import asyncio
# Standard python includes
import os
from typing import Optional, Tuple

import common.config as config
from common.constants import mercure_defs
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler
# Starlette-related includes
from starlette.templating import Jinja2Templates

redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
rq_slow_queue = Queue(name="mercure_slow", connection=redis)
rq_fast_queue = Queue(name="mercure_fast", connection=redis)
rq_fast_scheduler = Scheduler(queue=rq_fast_queue, connection=rq_fast_queue.connection)


def get_user_information(request) -> dict:
    """Returns dictionary of values that should always be passed to the templates when the user is logged in."""
    return {
        "logged_in": request.user.is_authenticated,
        "user": request.user.display_name,
        "is_admin": request.user.is_admin if request.user.is_authenticated else False,
        "appliance_name": config.mercure.appliance_name,
        "appliance_color": config.mercure.appliance_color,
    }


def get_mercure_version(request) -> dict:
    return {"mercure_version": mercure_defs.VERSION}


templates = Jinja2Templates(directory="webinterface/templates", context_processors=[get_user_information, get_mercure_version])


async def async_run(cmd, **params) -> Tuple[Optional[int], bytes, bytes]:
    """Executes the given command in a way compatible with ayncio."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **params
    )

    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout, stderr


async def async_run_exec(*args, **params) -> Tuple[Optional[int], bytes, bytes]:
    """Executes the given command in a way compatible with ayncio."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **params
    )

    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout, stderr
