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
import common.monitor as monitor
import common.helper as helper
import common.config as config
from common.constants import mercure_names
import traceback


logger = daiquiri.getLogger("process_series")


def process_series(folder):    
    logger.info(f'Now processing = {folder}')
    docker_client = docker.from_env()
    
    lock_file=Path(folder) / mercure_names.PROCESSING
    if lock_file.exists():
        logger.warning(f"Folder already contains lockfile {folder}/"+mercure_names.PROCESSING)
        return

    try:
        lock=helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f'Unable to create lock file {lock_file}')
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f'Unable to create lock file in processing folder {lock_file}')
        return 

    processing_success=False
    needs_dispatching=False

    # TODO: Perform the processing
    # time.sleep(10)
    def get_task():
        the_path = Path(folder) / mercure_names.TASKFILE
        if not the_path.exists():
            return None

        with open(the_path, "r") as f:
            return json.load(f)
    
    try:
        task = get_task()
        docker_image = task['process']['docker_tag']
        docker_client.containers.run(docker_image, 
            '--dicom-path /data',
            volumes={folder:{'bind':'/data','mode':'rw'}})
        processing_success = True
    except json.JSONDecodeError:
        logger.error("Task not valid.")
    except IndexError:
        logger.error("docker_tag not configured.")
    except docker.errors.ContainerError:
        logger.error("container exited with non-zero exit code")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Processing error: container exited with non-zero exit code.")
    except docker.errors.ImageNotFound:
        logger.error(f"Docker image {docker_image} not found")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Docker image {docker_image} not found")
    except:
        logger.info(f"Unknown processing failure")
    # Create a new lock file to ensure that no other process picks up the folder while copying
    lock_file=Path(folder) / mercure_names.LOCK
    try:
        lock_file.touch()
    except:
        logger.info(f"Error locking folder to be moved {folder}")        
        logger.error(traceback.format_exc())
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
        logger.error(traceback.format_exc())
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Error moving {source_folder} to {destination_folder}")


