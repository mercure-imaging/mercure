"""
process_series.py
=================
Helper functions for mercure's processor module
"""

# Standard python includes
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, cast, Optional
import json
import shutil
import daiquiri
from datetime import datetime
import docker
import traceback
import nomad
from jinja2 import Template

# App-specific includes
import common.monitor as monitor
import common.helper as helper
import common.config as config

from common.constants import mercure_names
from common.types import Task, TaskInfo, Module, Rule
import common.notification as notification
from common.version import mercure_version
from common.constants import (
    mercure_events,
)


logger = config.get_logger()


def nomad_runtime(task: Task, folder: str) -> bool:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)

    if not task.process:
        return False

    module: Module = cast(Module, task.process.module_config)

    f_path = Path(folder)
    if not module.docker_tag:
        logger.error("No docker tag supplied")
        return False

    with open("nomad/mercure-processor-template.nomad", "r") as f:
        rendered = Template(f.read()).render(
            image=module.docker_tag,
            mercure_tag=mercure_version.get_image_tag(),
            constraints=module.constraints,
            resources=module.resources,
            uid=os.getuid(),
        )
    logger.debug("----- job definition -----")
    logger.debug(rendered)
    try:
        job_definition = nomad_connection.jobs.parse(rendered)
    except nomad.api.exceptions.BadRequestNomadException as err:
        logger.error(err)
        print(err.nomad_resp.reason)
        print(err.nomad_resp.text)
        return False
    # logger.debug(job_definition)

    job_definition["ID"] = f"processor-{task.process.module_name}"
    job_definition["Name"] = f"processor-{task.process.module_name}"
    nomad_connection.job.register_job(job_definition["ID"], dict(Job=job_definition))

    meta = {"PATH": f_path.name}
    logger.debug(meta)
    job_info = nomad_connection.job.dispatch_job(f"processor-{task.process.module_name}", meta=meta)
    with open(f_path / "nomad_job.json", "w") as json_file:
        json.dump(job_info, json_file, indent=4)

    monitor.send_task_event(monitor.task_event.PROCESS_BEGIN, task.id, 0, "", "Processing job dispatched.")
    return True


docker_pull_throttle: Dict[str, datetime] = {}


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

    if helper.get_runner() == "docker":
        # We want to bind the correct path into the processor, but if we're inside docker we need to use the host path
        try:
            base_path = Path(docker_client.api.inspect_volume("mercure_data")["Options"]["device"])
        except Exception as e:
            base_path = Path("/opt/mercure/data")
            logger.error(f"Unable to find volume 'mercure_data'; assuming data directory is {base_path}")

        logger.info(f"Base path: {base_path}")
        real_folder = base_path / "processing" / real_folder.stem

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

    # Determine if Docker Hub should be checked for new module version (only once per hour)
    perform_image_update = True
    if docker_tag in docker_pull_throttle:
        timediff = datetime.now() - docker_pull_throttle[docker_tag]
        # logger.info("Time elapsed since update " + str(timediff.total_seconds()))
        if timediff.total_seconds() < 3600:
            perform_image_update = False

    # Get the latest image from Docker Hub
    if perform_image_update:
        try:
            docker_pull_throttle[docker_tag] = datetime.now()
            logger.info("Checking for update of docker image " + docker_tag + " ...")
            pulled_image = docker_client.images.pull(docker_tag)
            if pulled_image is not None:
                digest_string = (
                    pulled_image.attrs.get("RepoDigests")[0] if pulled_image.attrs.get("RepoDigests") else "None"
                )
                logger.info("Using DIGEST " + digest_string)
            # Clean dangling container images, which occur when the :latest image has been replaced
            prune_result = docker_client.images.prune(filters={"dangling": True})
            logger.info(prune_result)
            logger.info("Update done")
        except Exception as e:
            # Don't use ERROR here because the exception will be raised for all Docker images that
            # have been built locally and are not present in the Docker Registry.
            logger.info("Couldn't check for module update (this is normal for unpublished modules)")
            logger.info(e)

    # Run the container and handle errors of running the container
    processing_success = True
    try:
        logger.info("Now running container:")
        logger.info(
            {"docker_tag": docker_tag, "volumes": merged_volumes, "environment": environment, "arguments": arguments}
        )

        # nomad job dispatch -meta IMAGE_ID=alpine:3.11 -meta PATH=test  mercure-processor
        # nomad_connection.job.dispatch_job('mercure-processor', meta={"IMAGE_ID":"alpine:3.11", "PATH": "test"})

        # Run the container -- need to do in detached mode to be able to print the log output if container exits
        # with non-zero code while allowing the container to be removed after execution (with autoremoval and
        # non-detached mode, the log output is gone before it can be printed from the exception)
        uid_string = f"{os.getuid()}:{os.getegid()}"
        container = docker_client.containers.run(
            docker_tag,
            volumes=merged_volumes,
            environment=environment,
            **arguments,
            user=uid_string,
            group_add=[os.getegid()],
            detach=True,
        )
        monitor.send_task_event(
            monitor.task_event.PROCESS_BEGIN, task.id, 0, task.process.module_name, f"Processing job running."
        )
        # Wait for end of container execution
        docker_result = container.wait()
        logger.info(docker_result)

        # Print the log out of the module
        logger.info("=== MODULE OUTPUT - BEGIN ========================================")
        if container.logs() is not None:
            logger.info(container.logs().decode("utf-8"))
        logger.info("=== MODULE OUTPUT - END ==========================================")

        # Check if the processing was successful (i.e., container returned exit code 0)
        exit_code = docker_result.get("StatusCode")
        if exit_code != 0:
            logger.error(f"Error while running container {docker_tag} - exit code {exit_code}", task.id)  # handle_error
            processing_success = False

        # Remove the container now to avoid that the drive gets full
        container.remove()

    except docker.errors.APIError:
        # Something really serious happened
        logger.error(f"API error while trying to run Docker container, tag: {docker_tag}", task.id)  # handle_error
        processing_success = False

    except docker.errors.ImageNotFound:
        logger.error(f"Error running docker container. Image for tag {docker_tag} not found.", task.id)  # handle_error
        processing_success = False

    return processing_success


def process_series(folder) -> None:
    logger.info("----------------------------------------------------------------------------------")
    logger.info(f"Now processing {folder}")
    processing_success = False
    needs_dispatching = False

    lock_file = Path(folder) / mercure_names.PROCESSING
    lock = None
    task: Optional[Task] = None
    taskfile_path = Path(folder) / mercure_names.TASKFILE
    try:
        try:
            lock_file.touch(exist_ok=False)
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

        if not taskfile_path.exists():
            logger.error(f"Task file does not exist")
            raise Exception(f"Task file does not exist")

        with open(taskfile_path, "r") as f:
            task = Task(**json.load(f))

        if task.dispatch:
            needs_dispatching = True

        f_path = Path(folder)
        (f_path / "in").mkdir()
        for child in f_path.iterdir():
            if child.is_file() and child.name != ".processing":
                # logger.info(f"Moving {child}")
                child.rename(f_path / "in" / child.name)
        (f_path / "out").mkdir()
        if helper.get_runner() == "nomad" or config.mercure.process_runner == "nomad":
            logger.debug("Processing with Nomad.")
            # Use nomad if we're being run inside nomad, or we're configured to use nomad regardless
            processing_success = nomad_runtime(task, folder)
        elif helper.get_runner() in ("docker", "systemd"):
            logger.debug("Processing with Docker")
            # Use docker if we're being run inside docker or just by systemd
            processing_success = docker_runtime(task, folder)
        else:
            processing_success = False
            raise Exception("Unable to determine valid runtime for processing")
    except Exception as e:
        processing_success = False
        if task is not None:
            logger.error("Processing error.", task.id)  # handle_error
        else:
            try:
                task_id = json.load(open(taskfile_path, "r"))["id"]
                logger.error("Processing error.", task_id)  # handle_error
            except Exception:
                logger.error("Processing error.", None)  # handle_error
    finally:
        if task is not None:
            task_id = task.id
        else:
            task_id = "Unknown"
        if helper.get_runner() in ("docker", "systemd") and config.mercure.process_runner != "nomad":
            logger.info("Docker processing complete")
            # Copy the task to the output folder (in case the module didn't move it)
            push_input_task(f_path / "in", f_path / "out")
            # If configured in the rule, copy the input images to the output folder
            if task is not None and task.process and task.process.retain_input_images == "True":
                push_input_images(task_id, f_path / "in", f_path / "out")
            # Push the results either to the success or error folder
            move_results(task_id, folder, lock, processing_success, needs_dispatching)
            shutil.rmtree(folder, ignore_errors=True)

            if processing_success:
                monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, task_id, 0, "", "Processing job complete.")
                # If dispatching not needed, then trigger the completion notification (for docker/systemd)
                if not needs_dispatching:
                    monitor.send_task_event(monitor.task_event.COMPLETE, task_id, 0, "", "Task complete.")
                    # TODO: task really is never none if processing_success is true
                    trigger_notification(task, mercure_events.COMPLETION)  # type: ignore

            else:
                monitor.send_task_event(monitor.task_event.ERROR, task_id, 0, "", "Processing failed.")
                if task is not None:  # TODO: handle if task is none?
                    trigger_notification(task, mercure_events.ERROR)
        else:
            if processing_success:
                logger.info(f"Done submitting for processing")
            else:
                logger.info(f"Unable to process task")
                move_results(task_id, folder, lock, False, False)
                monitor.send_task_event(monitor.task_event.ERROR, task_id, 0, "", "Unable to process task")
                if task is not None:
                    trigger_notification(task, mercure_events.ERROR)
    return


def push_input_task(input_folder: Path, output_folder: Path):
    task_json = output_folder / "task.json"
    if not task_json.exists():
        try:
            shutil.copyfile(input_folder / "task.json", output_folder / "task.json")
        except:
            try:
                task_id = json.load(open(input_folder / "task.json", "r"))["id"]
                logger.error(f"Error copying task file to outfolder {output_folder}", task_id)  # handle_error
            except Exception:
                logger.error(f"Error copying task file to outfolder {output_folder}", None)  # handle_error


def push_input_images(task_id: str, input_folder: Path, output_folder: Path):
    error_while_copying = False
    for entry in os.scandir(input_folder):
        if entry.name.endswith(mercure_names.DCM):
            try:
                shutil.copyfile(input_folder / entry.name, output_folder / entry.name)
            except:
                logger.exception(f"Error copying file to outfolder {entry.name}")
                error_while_copying = True
                error_info = sys.exc_info()
    if error_while_copying:
        logger.error(
            f"Error while copying files to output folder {output_folder}", task_id, exc_info=error_info
        )  # handle_error


def move_results(
    task_id: str, folder: str, lock: Optional[helper.FileLock], processing_success: bool, needs_dispatching: bool
) -> None:
    # Create a new lock file to ensure that no other process picks up the folder while copying
    logger.debug(f"Moving results folder {folder} {'with' if needs_dispatching else 'without'} dispatching")
    lock_file = Path(folder) / mercure_names.LOCK
    if lock_file.exists():
        logger.error(f"Folder already contains lockfile {folder}/" + mercure_names.LOCK)
        return
    try:
        lock_file.touch(exist_ok=False)
    except Exception:
        logger.error(f"Error locking folder to be moved {folder}", task_id)  # handle_error

    if lock is not None:
        lock.free()

    if not processing_success:
        logger.debug(f"Failing: {folder}")
        move_out_folder(task_id, folder, config.mercure.error_folder, move_all=True)
    else:
        if needs_dispatching:
            logger.debug(f"Dispatching: {folder}")
            move_out_folder(task_id, folder, config.mercure.outgoing_folder)
        else:
            logger.debug(f"Success: {folder}")
            move_out_folder(task_id, folder, config.mercure.success_folder)


def move_out_folder(task_id: str, source_folder_str, destination_folder_str, move_all=False) -> None:
    source_folder = Path(source_folder_str)
    destination_folder = Path(destination_folder_str)

    target_folder = destination_folder / source_folder.name
    if target_folder.exists():
        target_folder = destination_folder / (source_folder.name + "_" + datetime.now().isoformat())

    logger.debug(f"Moving {source_folder} to {target_folder}, move_all: {move_all}")
    logger.debug("--- source contents ---")
    for k in source_folder.glob("**/*"):
        logger.debug("{:>25}".format(str(k.relative_to(source_folder))))
    logger.debug("--------------")
    try:
        if move_all:
            shutil.move(str(source_folder), target_folder)
        else:
            shutil.move(str(source_folder / "out"), target_folder)
            lockfile = source_folder / mercure_names.LOCK
            lockfile.unlink()

    except:
        logger.error(f"Error moving folder {source_folder} to {destination_folder}", task_id)  # handle_error


def trigger_notification(task: Task, event) -> None:
    task_info = task.info
    current_rule = task_info.get("applied_rule")
    logger.debug(f"Notification {event}")
    # Check if the rule is available
    if not current_rule:
        logger.error(f"Missing applied_rule in task file in task {task.id}", task.id)  # handle_error
        return

    # Check if the mercure configuration still contains that rule
    if not isinstance(config.mercure.rules.get(current_rule, ""), Rule):
        logger.error(
            f"Applied rule not existing anymore in mercure configuration from task {task.id}", task.id
        )  # handle_error
        return

    # Now fire the webhook if configured
    if event == mercure_events.RECEPTION:
        if config.mercure.rules[current_rule].notification_trigger_reception == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.RECEPTION,
                current_rule,
            )
    if event == mercure_events.COMPLETION:
        if config.mercure.rules[current_rule].notification_trigger_completion == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.COMPLETION,
                current_rule,
            )
    if event == mercure_events.ERROR:
        if config.mercure.rules[current_rule].notification_trigger_error == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.ERROR,
                current_rule,
            )
