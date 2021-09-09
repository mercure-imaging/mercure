import json
from pathlib import Path
import os
from typing import Any, Dict, cast, Optional
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
from common.types import EmptyDict, Task, Module
import traceback

import nomad

logger = daiquiri.getLogger("process_series")


def nomad_runtime(task: Task, folder: str) -> bool:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)

    if not task.process:
        return False

    module: Module = cast(Module, task.process.module_config)

    f_path = Path(folder)
    if not module.docker_tag:
        logger.error("No docker tag supplied")
        return False

    meta = {"IMAGE_ID": module.docker_tag, "PATH": f_path.name}
    logger.debug(meta)
    job_info = nomad_connection.job.dispatch_job("mercure-processor", meta=meta)
    with open(f_path / "nomad_job.json", "w") as json_file:
        json.dump(job_info, json_file, indent=4)

    return True


def docker_runtime(task: Task, folder: str) -> bool:
    docker_client = docker.from_env()

    if not task.process:
        return False

    module: Module = cast(Module, task.process.module_config)

    def decode_task(option: str) -> Any:
        option_dict: Any
        try:
            val = cast(str, module.get(option, "{}"))
            option_dict = json.loads(val)
        except json.decoder.JSONDecodeError:
            # The decoder bails if the JSON is an empty string
            option_dict = {}

        return option_dict

    real_folder = Path(folder)

    if config.get_runner() == "docker":
        # We want to bind the correct path into the processor, but if we're inside docker we need to use the host path
        # TODO: don't hardcode this!! can we use the mercure_data volume that docker knows about instead?
        # we don't want to just mount the whole mercure_data in though.
        real_folder = Path("/opt/mercure/data/processing") / real_folder.stem

    default_volumes = {
        str(real_folder / "in"): {"bind": "/data", "mode": "rw"},
        str(real_folder / "out"): {"bind": "/output", "mode": "rw"},
    }
    logger.debug(default_volumes)

    if module.docker_tag:
        docker_tag: str = module.docker_tag
    else:
        logger.error("No docker tag supplied")
        return False
    additional_volumes: Dict[str, Dict[str, str]] = decode_task("additional_volumes")
    environment = decode_task("environment")
    environment = {**environment, **dict(MERCURE_IN_DIR="/data", MERCURE_OUT_DIR="/output")}
    arguments = decode_task("arguments")

    # Merge the two dictionaries
    merged_volumes = {**default_volumes, **additional_volumes}

    processing_success = True
    # Run the container, handle errors of running the container
    try:
        logger.info("Will run:")
        logger.info(
            {"docker_tag": docker_tag, "volumes": merged_volumes, "environment": environment, "arguments": arguments}
        )

        # nomad job dispatch -meta IMAGE_ID=alpine:3.11 -meta PATH=test  mercure-processor
        # nomad_connection.job.dispatch_job('mercure-processor', meta={"IMAGE_ID":"alpine:3.11", "PATH": "test"})

        logs: bytes = docker_client.containers.run(
            docker_tag, volumes=merged_volumes, environment=environment, **arguments
        )
        # Returns: logs (stdout), pass stderr=True if you want stderr too.
        logger.info(logs)
        """Raises:	
            docker.errors.ContainerError - If the container exits with a non-zero exit code
            docker.errors.ImageNotFound - If the specified image does not exist.
            docker.errors.APIError - If the server returns an error."""
    except (docker.errors.APIError, docker.errors.ImageNotFound):
        # Something really serious happened
        logger.info("There was a problem running the specified Docker container")
        logger.error(traceback.format_exc())
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error starting Docker container {docker_tag}"
        )
        processing_success = False
    except docker.errors.ContainerError as err:
        logger.error(f"The container returned a non-zero exit code {err}")
        monitor.send_event(
            monitor.m_events.PROCESSING,
            monitor.severity.ERROR,
            f"Error while running Docker container {docker_tag} - {err.exit_status}",
        )
        processing_success = False
    return processing_success


def process_series(folder) -> None:
    logger.info(f"Now processing = {folder}")
    processing_success = False
    needs_dispatching = False

    lock_file = Path(folder) / mercure_names.PROCESSING
    lock = None
    try:
        try:
            lock_file.touch()
            # lock = helper.FileLock(lock_file)
        except Exception as e:
            # Can't create lock file, so something must be seriously wrong
            # Not sure what should happen here- trying to copy the case out probably won't work,
            # but if we do nothing we'll just loop forever
            logger.error(f"Unable to create lock file {lock_file}")
            monitor.send_event(
                monitor.m_events.PROCESSING,
                monitor.severity.ERROR,
                f"Unable to create lock file in processing folder {lock_file}",
            )
            raise e

        taskfile_path = Path(folder) / mercure_names.TASKFILE
        if not taskfile_path.exists():
            logger.error(f"Task file does not exist")
            raise Exception(f"Task file does not exist")

        with open(taskfile_path, "r") as f:
            task: Task = Task(**json.load(f))

        if task.dispatch:
            needs_dispatching = True

        f_path = Path(folder)
        (f_path / "in").mkdir()
        for child in f_path.iterdir():
            if child.is_file() and child.name != ".processing":
                # logger.info(f"Moving {child}")
                child.rename(f_path / "in" / child.name)
        (f_path / "out").mkdir()
        if config.get_runner() == "nomad" or config.mercure.process_runner == "nomad":
            # Use nomad if we're being run inside nomad, or we're configured to use nomad regardless
            processing_success = nomad_runtime(task, folder)
        elif config.get_runner() in ("docker", "systemd"):
            # Use docker if we're being run inside docker or just by systemd
            processing_success = docker_runtime(task, folder)
        else:
            processing_success = False
            raise Exception("Unable to determine a valid runtime for processing.")
    except Exception as e:
        logger.error("Processing error.")
        logger.error(traceback.format_exc())
    finally:
        if config.get_runner() in ("docker", "systemd") and config.mercure.process_runner != "nomad":
            logger.debug("Docker processing: immediately move results")
            move_results(folder, lock, processing_success, needs_dispatching)
            shutil.rmtree(folder, ignore_errors=True)

    logger.info(f"Done processing case")
    return


def move_results(
    folder: str, lock: Optional[helper.FileLock], processing_success: bool, needs_dispatching: bool
) -> None:
    # Create a new lock file to ensure that no other process picks up the folder while copying
    logger.debug(f"Moving results folder {folder}")
    lock_file = Path(folder) / mercure_names.LOCK
    if lock_file.exists():
        logger.error(f"Folder already contains lockfile {folder}/" + mercure_names.LOCK)
        return
    try:
        lock_file.touch()
    except:
        logger.info(f"Error locking folder to be moved {folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error locking folder to be moved {folder}"
        )
    if lock is not None:
        lock.free()

    if not processing_success:
        move_out_folder(folder, config.mercure.error_folder, move_all=True)
    else:
        if needs_dispatching:
            move_out_folder(folder, config.mercure.outgoing_folder)
        else:
            move_out_folder(folder, config.mercure.success_folder)


def move_out_folder(source_folder_str, destination_folder_str, move_all=False) -> None:
    source_folder = Path(source_folder_str)
    destination_folder = Path(destination_folder_str)

    target_folder = destination_folder / source_folder.name
    if target_folder.exists():
        target_folder = destination_folder / (source_folder.name + "_" + datetime.now().isoformat())

    logger.debug(f"Moving {source_folder} to {target_folder}, move_all: {move_all}")

    for k in source_folder.glob("**/*"):
        logger.debug(k.relative_to(source_folder))

    try:
        if move_all:
            shutil.move(str(source_folder), target_folder)
        else:
            shutil.move(str(source_folder / "out"), target_folder)
            lockfile = source_folder / mercure_names.LOCK
            lockfile.unlink()

    except:
        logger.info(f"Error moving folder {source_folder} to {destination_folder}")
        logger.error(traceback.format_exc())
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error moving {source_folder} to {destination_folder}"
        )
