"""
status.py
=========
Helper functions for mercure's processor module
"""

# Standard python includes
from pathlib import Path

# App-specific includes
from common.constants import mercure_names


def is_ready_for_processing(folder) -> bool:
    """Checks if a case in the processing folder is ready for the processor."""
    try:
        path = Path(folder)
        folder_status = (
            not (path / mercure_names.LOCK).exists()
            and not (path / mercure_names.PROCESSING).exists()
            and len(list(path.glob("*.dcm"))) > 0
        )
        return folder_status
    except:
        # Capture exceptions that may be triggered if the folder has been removed 
        # by another process in the meantime
        return False
