import json
from pathlib import Path
import os
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

logger = daiquiri.getLogger("process_series")


def process_series(folder):
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
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR,
                           f"Unable to create lock file in processing folder {lock_file}")
        return

    processing_success = True
    # TODO: Something needs to figure out whether to dispatch
    needs_dispatching = False

    the_path = Path(folder) / mercure_names.TASKFILE
    if not the_path.exists():
        logger.error(f"Task file does not exist")
        return

    with open(the_path, "r") as f:
        task = json.load(f)

    docker_tag = task["process"]["docker_tag"]
    if "dispatch" in task:
        needs_dispatching = True

    def decode_task(option):
        try:
            option_dict = json.loads(task["process"].get(option, "{}"))
        except json.decoder.JSONDecodeError:
            # The decoder bails if the JSON is an empty string
            option_dict = {}

        return option_dict

    additional_volumes = decode_task("additional_volumes")
    environment = decode_task("environment")
    arguments = decode_task("arguments")

    logger.info(docker_tag)
    default_volumes = {folder: {"bind": "/data", "mode": "rw"}}
    # Merge the two dictionaries
    merged_volumes = {**default_volumes, **additional_volumes}

    # Run the container, handle errors of running the container
    try:
        logs = docker_client.containers.run(docker_tag, volumes=merged_volumes, environment=environment, **arguments)
        # Returns: logs (stdout), pass stderr=True if you want stderr too.
        logger.info(logs)
        """Raises:	
            docker.errors.ContainerError – If the container exits with a non-zero exit code
            docker.errors.ImageNotFound – If the specified image does not exist.
            docker.errors.APIError – If the server returns an error."""
    except (docker.errors.APIError, docker.errors.ImageNotFound):
        # Something really serious happened
        logger.info("There was a problem running the specified Docker container")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.h_events.PROCESSING,
                           monitor.severity.ERROR,
                           f'Error starting Docker container {docker_tag}')
        processing_success = False
    except docker.errors.ContainerError as err:
        logger.info("The container returned a non-zero exit code")
        monitor.send_event(monitor.h_events.PROCESSING,
                           monitor.severity.ERROR,
                           f'Error while running Docker container {docker_tag} - {err.exit_status}')
        processing_success = False

    # Create a new lock file to ensure that no other process picks up the folder while copying
    lock_file = Path(folder) / mercure_names.LOCK
    try:
        lock_file.touch()
    except:
        logger.info(f"Error locking folder to be moved {folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.h_events.PROCESSING,
                           monitor.severity.ERROR,
                           f"Error locking folder to be moved {folder}")

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


def move_folder(source_folder_str, destination_folder_str):
    source_folder = Path(source_folder_str)
    destination_folder = Path(destination_folder_str)

    target_folder = destination_folder / source_folder.name
    if target_folder.exists():
        target_folder = destination_folder / (source_folder.name + "_" + datetime.now().isoformat())

    logger.debug(f"Moving {source_folder} to {target_folder}")
    try:
        shutil.move(source_folder, target_folder)
        lockfile = target_folder / mercure_names.LOCK
        lockfile.unlink()
    except:
        logger.info(f"Error moving folder {source_folder} to {destination_folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR,
                           f"Error moving {source_folder} to {destination_folder}")
