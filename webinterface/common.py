"""
common.py
=========
Helper functions for the graphical user interface of mercure.
"""

# Standard python includes
from typing import Optional, Tuple
import asyncio

# Starlette-related includes
from starlette.templating import Jinja2Templates


templates = Jinja2Templates(directory="webinterface/templates")


def get_user_information(request) -> dict:
    """Returns dictionary of values that should always be passed to the templates when the user is logged in."""
    return {
        "logged_in": request.user.is_authenticated,
        "user": request.user.display_name,
        "is_admin": request.user.is_admin if request.user.is_authenticated else False,
    }


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
