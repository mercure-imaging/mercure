import json
from pathlib import Path

from common.monitor import s_events, send_series_event
from common.constants import mercure_names


def is_ready_for_processing(folder):
    """Checks if a case in the processing folder is ready for the processor.
    """
    path = Path(folder)
    folder_status = (
        not (path / mercure_names.LOCK).exists()
        and not (path / mercure_names.PROCESSING).exists()
        and len(list(path.glob("*.dcm"))) > 0
    )
    return folder_status
