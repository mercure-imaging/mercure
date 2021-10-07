from typing import cast
from common.types import Task, TaskDispatch
import json
import time
from pathlib import Path

from common.constants import mercure_names


def increase_retry(source_folder, retry_max, retry_delay) -> bool:
    """Increases the retries counter and set the wait counter to a new time
    in the future.
    :return True if increase has been successful or False if maximum retries
    has been reached
    """
    target_json_path = Path(source_folder) / mercure_names.TASKFILE
    with open(target_json_path, "r") as file:
        task: Task = Task(**json.load(file))

    dispatch = cast(TaskDispatch, task.dispatch)
    dispatch.retries = (dispatch.get("retries") or 0) + 1
    dispatch.next_retry_at = time.time() + retry_delay

    if dispatch.retries >= retry_max:
        return False

    with open(target_json_path, "w") as file:
        json.dump(task.dict(), file)
    return True
