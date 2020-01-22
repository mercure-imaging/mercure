import json
import time
from pathlib import Path

from common.constants import mercure_names


def increase_retry(source_folder, retry_max, retry_delay):
    """ Increases the retries counter and set the wait counter to a new time
    in the future.
    :return True if increase has been successful or False if maximum retries
    has been reached
    """
    target_json_path = Path(source_folder) / "target.json"
    with open(target_json_path, "r") as file:
        target_json = json.load(file)

    target_json["retries"] = target_json.get("retries", 0) + 1
    target_json["next_retry_at"] = time.time() + retry_delay

    if target_json["retries"] >= retry_max:
        return False

    with open(target_json_path, "w") as file:
        json.dump(target_json, file)
    return True
