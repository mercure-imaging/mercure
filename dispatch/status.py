import json
from pathlib import Path
from typing import Any, Optional

from common.monitor import s_events, send_series_event
from common.constants import mercure_names
from common.types import Task


def is_ready_for_sending(folder) -> Optional[Any]:
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
    return False


def has_been_send(folder) -> bool:
    """Checks if the given folder has already been sent."""
    return (Path(folder) / mercure_names.SENDLOG).exists()


def is_target_json_valid(folder) -> Optional[Any]:
    """
    Checks if the task.json file exists and is also valid. Mandatory
    subkeys are target_ip, target_port and target_aet_target under the
    dispatch key
    """
    path = Path(folder) / mercure_names.TASKFILE
    if not path.exists():
        return None

    try:
        with open(path, "r") as f:
            target: Task = json.load(f)
    except:
        send_series_event(
            s_events.ERROR, "None", 0, "None", f"task.json has invalid format",
        )
        return None

    dispatch = target.get("dispatch", {})
    if not all([key in dispatch for key in ["target_ip", "target_port", "target_aet_target"]]):
        send_series_event(
            s_events.ERROR,
            dispatch.get("series_uid", "None"),  # type: ignore
            0,
            dispatch.get("target_name", "None"),  # type: ignore
            f"task.json is missing a mandatory key {target}",
        )
        return None
    return target["dispatch"]
