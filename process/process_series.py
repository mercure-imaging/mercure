import json
from pathlib import Path
import os
import uuid
import json
import shutil
import daiquiri
import time

import common.monitor as monitor
import common.helper as helper

logger = daiquiri.getLogger("process_series")


def process_series(folder):
    
    logger.info(f'Now processing = {folder}')

    lock_file=Path(folder + '/.processing')
    if lock_file.exists():
        logger.warning(f"Folder already contains lockfile {folder}/.processing")
        return

    try:
        lock=helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f'Unable to create lock file {lock_file}')
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f'Unable to create lock file in processing folder {lock_file}')
        return 

    time.sleep(60)

    # TODO: Move folder to error/dispatch/success

    return
