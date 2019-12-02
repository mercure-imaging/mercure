import json
from pathlib import Path

from common.monitor import s_events, send_series_event


def is_ready_for_processing(folder):
    """Checks if a case in the processing folder is ready for the processor.
    """
    path = Path(folder)
    folder_status = (
        not (path / ".lock").exists()
        and not (path / ".processing").exists()
        and len(list(path.glob("*.dcm"))) > 0
    )
    return folder_status
