import json
from pathlib import Path
import os
from typing import Optional, cast
import uuid
import json
import shutil
import daiquiri
import time
from datetime import datetime
import docker
import traceback

import common.monitor as monitor
import common.helper as helper
import common.config as config
from common.constants import mercure_names
from common.types import Module, Task

logger = daiquiri.getLogger("process_series")


def process_series(folder) -> None:
    logger.info(f"Now processing = {folder}")

    docker_client = docker.from_env()
    lock_file = Path(folder) / mercure_names.PROCESSING
    if lock_file.exists():
        logger.warning(f"Folder already contains lockfile {folder}/" + mercure_names.PROCESSING)
        return

    try:
        lock = helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f"Unable to create lock file {lock_file}")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Unable to create lock file in processing folder {lock_file}")
        return

    processing_success = True
    needs_dispatching = False

    # TODO: Perform the processing
    time.sleep(10)

    def get_task() -> Optional[Task]:
        the_path = Path(folder) / mercure_names.TASKFILE
        if not the_path.exists():
            return None

        with open(the_path, "r") as f:
            return cast(Task, json.load(f))

    task = get_task()

    assert task is not None
    process_info = cast(Module,task["process"])

    logger.info(process_info.get("docker_tag"))

    docker_client.containers.run(process_info["docker_tag"], "--dicom-path /data", volumes={folder: {"bind": "/data", "mode": "rw"}})

    # TODO: Error handling

    # Create a new lock file to ensure that no other process picks up the folder while copying
    lock_file = Path(folder) / mercure_names.LOCK
    try:
        lock_file.touch()
    except:
        logger.info(f"Error locking folder to be moved {folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error locking folder to be moved {folder}")

    # Remove the processing lock
    lock.free()

    if not processing_success:
        move_folder(folder, config.mercure["error_folder"])
    else:
        if needs_dispatching:
            move_folder(folder, config.mercure["outgoing_folder"])
        else:
            move_folder(folder, config.mercure["success_folder"])

    logger.info(f"Done processing case")
    return


def move_folder(source_folder_str, destination_folder_str) -> None:
    source_folder = Path(source_folder_str)
    destination_folder = Path(destination_folder_str)

    target_folder = destination_folder / source_folder.name
    if target_folder.exists():
        target_folder = destination_folder / (source_folder.name + "_" + datetime.now().isoformat())

    logger.debug(f"Moving {source_folder} to {target_folder}")
    try:
        shutil.move(str(source_folder), target_folder)
        lockfile = target_folder / mercure_names.LOCK
        lockfile.unlink()
    except:
        logger.info(f"Error moving folder {source_folder} to {destination_folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error moving {source_folder} to {destination_folder}")
