import json
import os
import logging
from pathlib import Path
from passlib.apps import custom_app_context as pwd_context
import daiquiri

from common.constants import mercure_names


daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("users")

users_timestamp = 0
users_filename = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/../configuration/users.json")

users_list = {}


def read_users():
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
        create_users()


def create_users():
    """Create new users file and create seed admin account with name "admin" and password "router"."""
    logger.info("No user file found. Creating user list with seed admin account.")
    global users_list
    users_list = {"admin": {"password": hash_password("router"), "is_admin": "True", "change_password": "True"}}
    save_users()


def save_users():
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


def evaluate_password(username, password):
    """Check if the given password for the given user is correct. Hashed passwords are stored with salt."""
    if (len(username) == 0) or (len(password) == 0):
        return False

    if not username in users_list:
        return False

    stored_password = users_list[username].get("password", "")
    if len(stored_password) == 0:
        return False

    try:
        if pwd_context.verify(password, stored_password):
            return True
        else:
            return False
    except:
        return False


def hash_password(password):
    """Hash the password using the passlib library."""
    return pwd_context.hash(password)


def is_admin(username):
    """Check in the user list if the given user has admin rights."""
    if not username in users_list:
        return False

    if users_list[username].get("is_admin", "False") == "True":
        return True
    else:
        return False


def needs_change_password(username):
    """Check if the given user has to change his password after login."""
    if not username in users_list:
        return False

    if users_list[username].get("change_password", "False") == "True":
        return True
    else:
        return False
