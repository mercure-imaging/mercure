import json
import time
from pathlib import Path
from typing import Dict, Union, cast

from common.constants import mercure_names
from common.types import EmptyDict, Task, TaskDispatch, TaskDispatchStatus


def increase_retry(source_folder, retry_max, retry_delay) -> bool:
    """Increases the retries counter and set the wait counter to a new time
    in the future.
    :return True if increase has been successful or False if maximum retries
    has been reached
    """
    target_json_path = Path(source_folder) / mercure_names.TASKFILE
    task = Task.from_file(target_json_path)

    dispatch = cast(TaskDispatch, task.dispatch)
    dispatch.retries = (dispatch.get("retries") or 0) + 1
    dispatch.next_retry_at = time.time() + retry_delay

    if dispatch.retries >= retry_max:
        return False

    task.to_file(target_json_path)

    return True


def update_dispatch_status(source_folder: Path, status: Union[Dict[str, TaskDispatchStatus], EmptyDict]) -> bool:
    target_json_path: Path = source_folder / mercure_names.TASKFILE
    try:
        task = Task.from_file(target_json_path)

        dispatch = cast(TaskDispatch, task.dispatch)
        dispatch.status = status

        task.to_file(target_json_path)
    except Exception:
        return False

    return True
