"""
users.py
========
Users page and user support functions for the graphical user interface of mercure.
"""

# Standard python includes
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, cast

import common.config as config
import common.monitor as monitor
# App-specific includes
from common.constants import mercure_names
from decoRouter import Router as decoRouter
from mypy_extensions import TypedDict
from passlib.apps import custom_app_context as pwd_context
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from typing_extensions import Literal
from webinterface.common import templates

router = decoRouter()

###################################################################################
# Helper functions
###################################################################################


class User(TypedDict, total=False):
    email: str
    password: str
    is_admin: Literal["True", "False"]
    change_password: Literal["True", "False"]
    permissions: Any


logger = config.get_logger()

# passlib is way too chatty in debug mode
logging.getLogger("passlib").setLevel(logging.INFO)

users_timestamp: float = 0.0
users_filename = (os.getenv("MERCURE_CONFIG_FOLDER") or "/opt/mercure/config") + "/users.json"

users_list: Dict[str, User] = {}


def read_users() -> Dict[str, User]:
    """Reads the user list from the configuration file. The file will only be read if it has been updated since the last
    function call. If the file does not exist, create a new user file."""
    global users_list
    global users_timestamp
    users_file = Path(users_filename)

    # Check for existence of lock file
    lock_file = Path(users_file.parent / users_file.stem).with_suffix(mercure_names.LOCK)

    if lock_file.exists():
        raise ResourceWarning(f"Users file locked: {lock_file}")

    if users_file.exists():
        # Get the modification date/time of the configuration file
        stat = os.stat(users_filename)
        try:
            timestamp = stat.st_mtime
        except AttributeError:
            timestamp = 0

        # Check if the configuration file is newer than the version
        # loaded into memory. If not, return
        if timestamp <= users_timestamp:
            return users_list

        logger.info(f"Reading users from: {users_filename}")

        with open(users_file, "r") as json_file:
            users_list = json.load(json_file)
            users_timestamp = timestamp
            return users_list
    else:
        return create_users()


def create_users() -> Dict[str, User]:
    """Create new users file and create seed admin account with name "admin" and password "router"."""
    logger.info("No user file found. Creating user list with seed admin account.")
    global users_list
    users_list = {"admin": {"password": hash_password("router"), "is_admin": "True", "change_password": "True"}}
    save_users()
    return users_list


def save_users() -> None:
    """Write the users list into a file on the disk."""
    global users_list
    global users_timestamp
    users_file = Path(users_filename)

    # Check for existence of lock file
    lock_file = Path(users_file.parent / users_file.stem).with_suffix(mercure_names.LOCK)

    if lock_file.exists():
        raise ResourceWarning(f"Users file locked: {lock_file}")

    with open(users_file, "w") as json_file:
        json.dump(users_list, json_file, indent=4)

    try:
        stat = os.stat(users_filename)
        users_timestamp = stat.st_mtime
    except AttributeError:
        users_timestamp = 0

    logger.info(f"Stored user list into: {users_filename}")


def evaluate_password(username, password) -> bool:
    """Check if the given password for the given user is correct. Hashed passwords are stored with salt."""
    if (len(username) == 0) or (len(password) == 0):
        return False

    if username not in users_list:
        return False

    stored_password = users_list[username].get("password", "")
    if len(stored_password) == 0:
        return False

    try:
        if pwd_context.verify(password, stored_password):
            return True
        else:
            return False
    except Exception:
        return False


def hash_password(password) -> str:
    """Hash the password using the passlib library."""
    return cast(str, pwd_context.hash(password))


def is_admin(username) -> bool:
    """Check in the user list if the given user has admin rights."""
    if username not in users_list:
        return False

    if users_list[username].get("is_admin", "False") == "True":
        return True
    else:
        return False


def needs_change_password(username) -> bool:
    """Check if the given user has to change his password after login."""
    if username not in users_list:
        return False

    if users_list[username].get("change_password", "False") == "True":
        return True
    else:
        return False


###################################################################################
# Users endpoints
###################################################################################


@router.get("/")
@requires(["authenticated", "admin"], redirect="homepage")
async def show_users(request) -> Response:
    """Shows all available users."""
    try:
        read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    template = "users.html"
    context = {"request": request, "page": "users", "users": users_list}
    return templates.TemplateResponse(template, context)


@router.post("/")
@requires(["authenticated", "admin"], redirect="homepage")
async def add_new_user(request) -> Response:
    """Creates a new user and redirects to the user-edit page."""
    try:
        read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    newuser = form.get("name", "")
    if newuser in users_list:
        return PlainTextResponse("User already exists.")

    newpassword = hash_password(form.get("password", "here_should_be_a_password"))
    users_list[newuser] = {"password": newpassword, "is_admin": "False", "change_password": "True"}

    try:
        save_users()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write user list. Try again.")

    logger.info(f"Created user {newuser}")
    monitor.send_webgui_event(monitor.w_events.USER_CREATE, request.user.display_name, newuser)
    return RedirectResponse(url="/users/edit/" + newuser, status_code=303)


@router.get("/edit/{user}")
@requires(["authenticated", "admin"], redirect="login")
async def users_edit(request) -> Response:
    """Shows the settings for a given user."""
    try:
        read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edituser = request.path_params["user"]

    if edituser not in users_list:
        return RedirectResponse(url="/users", status_code=303)

    template = "users_edit.html"
    context = {
        "request": request,
        "page": "users",
        "edituser": edituser,
        "edituser_info": users_list[edituser],
    }
    return templates.TemplateResponse(template, context)


@router.post("/edit/{user}")
@requires(["authenticated"], redirect="login")
async def users_edit_post(request) -> Response:
    """Updates the given user with settings passed as form parameters."""
    try:
        read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edituser = request.path_params["user"]
    form = dict(await request.form())

    if edituser not in users_list:
        return PlainTextResponse("User does not exist anymore.")

    to_edit = users_list[edituser]
    to_edit["email"] = form["email"]
    if form["password"]:
        to_edit["password"] = hash_password(form["password"])
        to_edit["change_password"] = "False"

    # Only admins are allowed to change the admin status, and the current user
    # cannot change the status for himself (which includes the settings page)
    if request.user.is_admin and (request.user.display_name != edituser):
        to_edit["is_admin"] = form["is_admin"]

    if request.user.is_admin and form.get("permissions", ""):
        to_edit["permissions"] = form["permissions"]

    try:
        save_users()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write user list. Try again.")

    logger.info(f"Edited user {edituser}")
    monitor.send_webgui_event(monitor.w_events.USER_EDIT, request.user.display_name, edituser)
    if "own_settings" in form:
        return RedirectResponse(url="/", status_code=303)
    else:
        return RedirectResponse(url="/users", status_code=303)


@router.post("/delete/{user}")
@requires(["authenticated", "admin"], redirect="login")
async def users_delete_post(request) -> Response:
    """Deletes the given users."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    deleteuser = request.path_params["user"]

    if deleteuser in users_list:
        del users_list[deleteuser]

    try:
        save_users()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write user list. Try again.")

    logger.info(f"Deleted user {deleteuser}")
    monitor.send_webgui_event(monitor.w_events.USER_DELETE, request.user.display_name, deleteuser)
    return RedirectResponse(url="/users", status_code=303)

users_app = Starlette(routes=router)
