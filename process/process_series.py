import json
from pathlib import Path
import os
import uuid
import json
import shutil
import daiquiri

from common.monitor import s_events, send_series_event

logger = daiquiri.getLogger("process_series")

def process_series(folder):
    
    logger.info(f'Now processing = {folder}')

    return
