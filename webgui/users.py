import json
import os
from pathlib import Path


users_timestamp = 0
users_filename  = os.path.realpath(os.path.dirname(os.path.realpath(__file__))+'/../configuration/users.json')

users_list = {}


def read_users():
    global users_list
    global users_timestamp    
    users_file = Path(users_filename)

    # Check for existence of lock file
    lock_file=Path(users_file.parent/users_file.stem).with_suffix(".lock")

    if lock_file.exists():
        raise ResourceWarning(f"Users file locked: {lock_file}")

    if users_file.exists():
        # Get the modification date/time of the configuration file
        stat = os.stat(users_filename)
        try:
            timestamp=stat.st_mtime
        except AttributeError:
            timestamp=0

        # Check if the configuration file is newer than the version
        # loaded into memory. If not, return
        if timestamp <= users_timestamp:
            return users_list               

        print("Reading users from: ", users_filename)

        with open(users_file, "r") as json_file:
            users_list=json.load(json_file)
            users_timestamp=timestamp
            return users_list
    else:
        raise FileNotFoundError(f"Users file not fould: {users_file}")


def save_users():
    global users_list
    global users_timestamp    
    users_file = Path(users_filename)

    # Check for existence of lock file
    lock_file=Path(users_file.parent/users_file.stem).with_suffix(".lock")

    if lock_file.exists():
        raise ResourceWarning(f"Users file locked: {lock_file}")

    with open(users_file, "w") as json_file:
        json.dump(users_list,json_file, indent=4)

    try:
        stat = os.stat(users_filename)
        users_timestamp=stat.st_mtime
    except AttributeError:
        users_timestamp=0

    print("Stored user list into: ", users_filename)


def evaluate_password(username, password):
    if (len(username)==0) or (len(password)==0):
        return False

    if not username in users_list:
        return False

    stored_password=users_list[username].get("password","")
    if len(stored_password)==0:
        return False

    # TODO: Implement hashing of passwords

    if password==stored_password:
        return True
    else:
        return False


def is_admin(username):
    if not username in users_list:
        return False

    if users_list[username].get("is_admin","False")=="True":
        return True
    else:
        return False
