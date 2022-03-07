"""
status.py
=========
Helper functions for dispatching processed cases
"""

# Standard python includes
import json
from pathlib import Path
from typing import Optional
import daiquiri
from common import monitor

# App-specific includes
from common.monitor import s_events
from common.constants import mercure_names
from common.types import Task

logger = daiquiri.getLogger("status")


def is_ready_for_sending(folder) -> Optional[Task]:
    """Checks if a case in the outgoing folder is ready for sending by the dispatcher.

    No lock file (.lock) should be in sending folder and no error file (.error),
    if there is one copy/move is not done yet. Also at least some dicom files
    should be there for sending. Also checks for a task.json file and if it is
    valid.
    """
    path = Path(folder)
    folder_status = (
        not (path / mercure_names.LOCK).exists()
        and not (path / mercure_names.ERROR).exists()
        and not (path / mercure_names.PROCESSING).exists()
        and len(list(path.glob(mercure_names.DCMFILTER))) > 0
    )
    content = is_target_json_valid(folder)

    if folder_status and content:
        return content
    return None


def has_been_send(folder) -> bool:
    """Checks if the given folder has already been sent."""
    return (Path(folder) / mercure_names.SENDLOG).exists()


def is_target_json_valid(folder) -> Optional[Task]:
    """
    Checks if the task.json file exists and is valid. Returns the content
    of the file (or None if the file is invalid)
    """
    path = Path(folder) / mercure_names.TASKFILE
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            target = Task(**json.load(f))
    except:
        logger.exception("task.json has invalid format")
        monitor.send_task_event(
            s_events.ERROR,
            "TODO",
            0,
            "None",
            f"task.json has invalid format",
        )
        return None
    return target or None
    # dispatch = target.dispatch.dict() if target.dispatch else {}
    # if not all([key in dispatch for key in ["target_ip", "target_port", "target_aet_target"]]):
    #     send_series_event(
    #         s_events.ERROR,
    #         dispatch.get("series_uid", "None"),  # type: ignore
    #         0,
    #         dispatch.get("target_name", "None"),  # type: ignore
    #         f"task.json is missing a mandatory key {target}",
    #     )
    #     return None
    # return target.dispatch or None
