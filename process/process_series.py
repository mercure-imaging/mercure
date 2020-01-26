import json
from pathlib import Path
import os
import uuid
import json
import shutil
import daiquiri
import time
from datetime import datetime

import common.monitor as monitor
import common.helper as helper
import common.config as config
from common.constants import mercure_names


logger = daiquiri.getLogger("process_series")


def process_series(folder):    
    logger.info(f'Now processing = {folder}')

    lock_file=Path(folder / mercure_names.PROCESSING)
    if lock_file.exists():
        logger.warning(f"Folder already contains lockfile {folder}/"+mercure_names.PROCESSING)
        return

    try:
        lock=helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f'Unable to create lock file {lock_file}')
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f'Unable to create lock file in processing folder {lock_file}')
        return 

    processing_success=True
    needs_dispatching=False

    # TODO: Perform the processing
    time.sleep(10)

    # TODO: Error handling

    # Create a new lock file to ensure that no other process picks up the folder while copying
    try:
        lock_file=lock_file=Path(folder / mercure_names.LOCK_EXTENSION)
        lock_file.touch()
    except:
        logger.info(f"Error locking folder to be moved {folder}")        
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Error locking folder to be moved {folder}")

    # Remove the processing lock
    lock.free()

    if not processing_success:
        move_folder(folder, config.mercure['error_folder'])        
    else:
        if needs_dispatching:
            move_folder(folder, config.mercure['outgoing_folder'])   
        else:
            move_folder(folder, config.mercure['success_folder'])   

    logger.info(f'Done processing case')
    return


def move_folder(source_folder_str, destination_folder_str):

    source_folder=Path(source_folder_str)
    destination_folder=Path(destination_folder_str)

    target_folder=destination_folder / source_folder.name
    if target_folder.exists():
        target_folder=destination_folder / (source_folder.name + "_" + datetime.now().isoformat())

    logger.debug(f"Moving {source_folder} to {target_folder}")
    try:
        shutil.move(source_folder, target_folder)        
        lockfile=target_folder / mercure_names.LOCK
        lockfile.unlink()
    except:
        logger.info(f"Error moving folder {source_folder} to {destination_folder}")        
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Error moving {source_folder} to {destination_folder}")


