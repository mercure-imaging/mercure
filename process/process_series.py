"""
process_series.py
=================
Helper functions for mercure's processor module
"""

# Standard python includes
from genericpath import isfile
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Dict, List, cast, Optional
import json
import shutil
import daiquiri
from datetime import datetime
import docker
from docker.models.containers import Container

import traceback
import nomad
from jinja2 import Template

# App-specific includes
import common.monitor as monitor
import common.helper as helper
import common.config as config

from common.constants import mercure_names
from common.types import Task, TaskInfo, Module, Rule, TaskProcessing
import common.notification as notification
from common.version import mercure_version
import common.log_helpers as log_helpers
from common.constants import (
    mercure_events,
)


logger = config.get_logger()


async def nomad_runtime(task: Task, folder: Path, file_count_begin: int, task_processing:TaskProcessing) -> bool:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5) # type: ignore

    if not task.process:
        return False

    module: Module = cast(Module, task_processing.module_config)

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
    except nomad.api.exceptions.BadRequestNomadException as err: # type: ignore
        logger.error(err)
        print(err.nomad_resp.reason)
        print(err.nomad_resp.text)
        return False
    # logger.debug(job_definition)

    job_definition["ID"] = f"processor-{task_processing.module_name}"
    job_definition["Name"] = f"processor-{task_processing.module_name}"
    nomad_connection.job.register_job(job_definition["ID"], dict(Job=job_definition))

    meta = {"PATH": folder.name}
    logger.debug(meta)
    job_info = nomad_connection.job.dispatch_job(f"processor-{task_processing.module_name}", meta=meta)
    with open(folder / "nomad_job.json", "w") as json_file:
        json.dump(job_info, json_file, indent=4)

    monitor.send_task_event(
        monitor.task_event.PROCESS_BEGIN,
        task.id,
        file_count_begin,
        task_processing.module_name,
        "Processing job dispatched",
    )
    return True


docker_pull_throttle: Dict[str, datetime] = {}


async def docker_runtime(task: Task, folder: Path, file_count_begin: int, task_processing:TaskProcessing) -> bool:
    docker_client = docker.from_env()  # type: ignore

    if not task.process:
        return False

    module: Module = cast(Module, task_processing.module_config)

    def decode_task_json(json_string: Optional[str]) -> Any:
        if not json_string:
            return {}
        try:
            return json.loads(json_string)
        except json.decoder.JSONDecodeError:
            logger.error(f"Unable to convert JSON string {json_string}")
            return {}

    real_folder = folder    

    if helper.get_runner() == "docker":
        # We want to bind the correct path into the processor, but if we're inside docker we need to use the host path
        try:
            base_path = Path(docker_client.api.inspect_volume("mercure_data")["Options"]["device"])
        except Exception as e:
            base_path = Path("/opt/mercure/data")
            logger.error(f"Unable to find volume 'mercure_data'; assuming data directory is {base_path}")

        logger.info(f"Base path: {base_path}")
        real_folder = base_path / "processing" / real_folder.stem

    container_in_dir = "/tmp/data"
    container_out_dir = "/tmp/output"
    default_volumes = {
        str(real_folder / "in"): {"bind": container_in_dir, "mode": "rw"},
        str(real_folder / "out"): {"bind": container_out_dir, "mode": "rw"},
    }
    logger.debug(default_volumes)

    if module.docker_tag:
        docker_tag: str = module.docker_tag
    else:
        logger.error("No docker tag supplied")
        return False
      
    runtime = {}
    if config.mercure.processing_runtime:
        runtime = dict(runtime=config.mercure.processing_runtime)
        
    additional_volumes: Dict[str, Dict[str, str]] = decode_task_json(module.additional_volumes)
    module_environment = decode_task_json(module.environment)
    mercure_environment = dict(MERCURE_IN_DIR=container_in_dir, MERCURE_OUT_DIR=container_out_dir)
    monai_environment = dict(MONAI_INPUTPATH=container_in_dir, MONAI_OUTPUTPATH=container_out_dir,
                             HOLOSCAN_INPUT_PATH=container_in_dir, HOLOSCAN_OUTPUT_PATH=container_out_dir)

    environment = {**module_environment, **mercure_environment, **monai_environment}
    arguments = decode_task_json(module.docker_arguments)

    set_command = {}
    image_is_monai_map = False
    try:
        monai_app_manifest = json.loads(docker_client.containers.run(docker_tag, command="cat /etc/monai/app.json", entrypoint="").decode('utf-8'))
        image_is_monai_map = True
        set_command = dict(entrypoint="",command=monai_app_manifest["command"])
        logger.debug("Detected MONAI MAP, using command from manifest.")
    except docker.errors.ContainerError:
        pass
    except docker.errors.NotFound:
        raise Exception(f"Docker tag {docker_tag} not found, aborting.") from None
    except (json.decoder.JSONDecodeError, KeyError):
        raise Exception("Failed to parse MONAI app manifest.")
    
    module.requires_root = module.requires_root or image_is_monai_map

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

    # Run the container and handle errors of running the container
    processing_success = True
    container = None
    try:
        logger.info("Now running container:")
        logger.info(
            {"docker_tag": docker_tag, "volumes": merged_volumes, "environment": environment, "arguments": arguments}
        )

        # nomad job dispatch -meta IMAGE_ID=alpine:3.11 -meta PATH=test  mercure-processor
        # nomad_connection.job.dispatch_job('mercure-processor', meta={"IMAGE_ID":"alpine:3.11", "PATH": "test"})

        await monitor.async_send_task_event(
            monitor.task_event.PROCESS_MODULE_BEGIN,
            task.id,
            file_count_begin,
            task_processing.module_name,
            f"Processing module running",
        )

        # Run the container -- need to do in detached mode to be able to print the log output if container exits
        # with non-zero code while allowing the container to be removed after execution (with autoremoval and
        # non-detached mode, the log output is gone before it can be printed from the exception)

        user_info = dict(
            user=f"{os.getuid()}:{os.getegid()}",
            group_add=[os.getgid()]
        )
        if module.requires_root:
            if not config.mercure.support_root_modules:
                raise Exception("This module requires execution as root, but 'support_root_modules' is not set to true in the configuration. Aborting.")
            user_info = {}
            logger.debug("Executing module as root.")
        else:
            logger.debug("Executing module as mercure.")

        # We might be operating in a user-remapped namespace. This makes sure that the user inside the container can read and write the files.
        ( folder / "in" ).chmod(0o777)
        try:
            for k in ( real_folder / "in" ).glob("**/*"):
                k.chmod(0o666)
        except PermissionError:
            raise Exception("Unable to prepare input files for processor. The receiver may be running as root, which is no longer supported. ")
        ( folder / "out" ).chmod(0o777)

        container  = docker_client.containers.run(
            docker_tag,
            volumes=merged_volumes,
            environment=environment,
            **runtime,
            **set_command,
            **arguments,
            **user_info,
            detach=True,
        )

        # Wait for end of container execution
        docker_result = container.wait()
        logger.info(docker_result)

        # Print the log out of the module
        logger.info("=== MODULE OUTPUT - BEGIN ========================================")
        if container.logs() is not None:
            logs = container.logs().decode("utf-8")
            if not config.mercure.processing_logs.discard_logs:
                monitor.send_process_logs(task.id, task_processing.module_name, logs)
            logger.info(logs)
        logger.info("=== MODULE OUTPUT - END ==========================================")

        # In lieu of making mercure a sudoer...
        logger.debug("Changing the ownership of the output directory...")
        try:
            if (datetime.now() - docker_pull_throttle.get("busybox:stable-musl",datetime.fromisocalendar(1,1,1))).total_seconds() > 86400:
                docker_client.images.pull("busybox:stable-musl")
                docker_pull_throttle["busybox:stable_musl"] = datetime.now()
        except:
            logger.exception("could not pull busybox")

        if helper.get_runner() != "docker":
            # We need to set the owner to the "real", unremapped mercure user that lives outside of the container, ie our actual uid.
            # If docker isn't in usrns remap mode then this shouldn't have an effect.
            set_usrns_mode = { "userns_mode": "host" } 
        else:
            # We're running inside docker, so we need to set the owner to our actual uid inside this container (probably 1000), not the one outside.
            # If docker is in userns remap mode then this will get mapped, which is what we want. 
            set_usrns_mode = {}
        docker_client.containers.run(
            "busybox:stable-musl",
            volumes=merged_volumes,
            **set_usrns_mode,
            command=f"chown -R {os.getuid()}:{os.getegid()} {container_out_dir}",
            detach=True
        )

        # Reset the permissions to owner rwx, world readonly. 
        ( folder / "out" ).chmod(0o755)
        for k in ( folder / "out" ).glob("**/*"):
            if k.is_dir():
                k.chmod(0o755)

        for k in ( folder / "out" ).glob("**/*"):
            if k.is_file():
               k.chmod(0o644)

        await monitor.async_send_task_event(
            monitor.task_event.PROCESS_MODULE_COMPLETE,
            task.id,
            file_count_begin,
            task_processing.module_name,
            f"Processing module complete",
        )

        # Check if the processing was successful (i.e., container returned exit code 0)
        exit_code = docker_result.get("StatusCode")
        if exit_code != 0:
            logger.error(f"Error while running container {docker_tag} - exit code {exit_code}", task.id)  # handle_error
            processing_success = False

    except docker.errors.APIError: # type: ignore
        # Something really serious happened
        logger.error(f"API error while trying to run Docker container, tag: {docker_tag}", task.id)  # handle_error
        processing_success = False

    except docker.errors.ImageNotFound: # type: ignore
        logger.error(f"Error running docker container. Image for tag {docker_tag} not found.", task.id)  # handle_error
        processing_success = False
    finally:
        if container:
            # Remove the container now to avoid that the drive gets full
            container.remove()

    return processing_success


@log_helpers.clear_task_decorator_async
async def process_series(folder: Path) -> None:
    logger.info("----------------------------------------------------------------------------------")
    logger.info(f"Now processing {folder}")
    processing_success = False
    needs_dispatching = False


    lock_file = folder / mercure_names.PROCESSING
    lock = None
    task: Optional[Task] = None
    taskfile_path = folder / mercure_names.TASKFILE
    outputs = []

    try:
        try:
            lock_file.touch(exist_ok=False)
            # lock = helper.FileLock(lock_file)
        except FileExistsError:
            # Return if the case has already been locked by another instance in the meantime
            return           
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
        logger.setTask(task.id)
        if task.dispatch:
            needs_dispatching = True

        # Remember the number of incoming DCM files (for logging purpose)
        file_count_begin = len(list(folder.glob(mercure_names.DCMFILTER)))

        (folder / "in").mkdir()
        for child in folder.iterdir():
            if child.is_file() and child.name != ".processing":
                # logger.info(f"Moving {child}")
                child.rename(folder / "in" / child.name)
        (folder / "out").mkdir()

        if helper.get_runner() == "nomad" or config.mercure.process_runner == "nomad":
            logger.debug("Processing with Nomad.")
            # Use nomad if we're being run inside nomad, or we're configured to use nomad regardless
            runtime = nomad_runtime
        elif helper.get_runner() in ("docker", "systemd"):
            logger.debug("Processing with Docker")
            # Use docker if we're being run inside docker or just by systemd
            runtime = docker_runtime
        else:
            processing_success = False
            raise Exception("Unable to determine valid runtime for processing")
        
        if runtime == docker_runtime: # docker runtime might run several processing steps, need to put this event here
            await monitor.async_send_task_event(
                monitor.task_event.PROCESS_BEGIN,
                task.id,
                file_count_begin,
                (task.process[0].module_name if isinstance(task.process,list) else task.process.module_name) if task.process else "UNKNOWN",
                f"Processing job running",
            )
        # There are multiple processing steps
        if runtime == docker_runtime and isinstance(task.process,list):
            if task.process[0].retain_input_images: # Keep a copy of the input files
                shutil.copytree(folder / "in", folder / "input_files")
            logger.info("==== TASK ====",task.dict())
            copied_task = task.copy(deep=True)
            try:
                for i, task_processing in enumerate(task.process):
                    # As far as the processing step is concerned, theres' only one processing step and it's this one,
                    # so we copy this one's information into a copy of the task file and hand that to the container.
                    copied_task.process = task_processing

                    with open(folder / "in" / mercure_names.TASKFILE,"w") as task_file:
                        json.dump(copied_task.dict(), task_file)

                    processing_success = await docker_runtime(task, folder, file_count_begin, task_processing)
                    if not processing_success:
                        break
                    output = handle_processor_output(task, task_processing, i, folder)
                    outputs.append((task_processing.module_name,output))
                    (folder / "out" / "result.json").unlink(missing_ok=True)
                    shutil.rmtree(folder / "in")
                    if i < len(task.process)-1: # Move the results of the processing step to the input folder of the next one
                        (folder / "out").rename(folder / "in")
                        (folder / "out").mkdir()
                    task_processing.output = output
                # Done all steps
                if task.process[0].retain_input_images:
                    (folder / "input_files").rename(folder / "in")
                
                if outputs:
                    with open(folder / "out" / "result.json","w") as fp:
                        json.dump(outputs, fp, indent=4)

            finally:
                with open(folder / "out" / mercure_names.TASKFILE,"w") as task_file:
                    #  logger.warning(f"DUMPING to {folder / 'out' / mercure_names.TASKFILE} TASK {task=}")
                     json.dump(task.dict(), task_file, indent=4)
        elif isinstance(task.process,list):
            raise Exception("Multiple processing steps are only supported on the Docker runtime.")
        else:
            task_process = cast(TaskProcessing,task.process)
            processing_success = await runtime(task, folder, file_count_begin, task_process)
            if processing_success:
                output = handle_processor_output(task, task_process, 0, folder)
                task.process.output = output # type: ignore
                with open(folder / "out" / mercure_names.TASKFILE,"w") as fp:
                    # logger.warning(f"DUMPING to {folder / 'out' / mercure_names.TASKFILE} TASK {task=}")
                    json.dump(task.dict(), fp, indent=4)
                outputs.append((task_process.module_name,output))
        
    except Exception as e:
        processing_success = False
        task_id = None
        if task is not None:
            task_id = task.id
        else:
            try:
                task_id = json.load(open(taskfile_path, "r"))["id"]
            except:
                pass
        logger.error("Processing error.", task_id)  # handle_error
    finally:
        if task is not None:
            task_id = task.id
        else:
            task_id = "Unknown"
        if helper.get_runner() in ("docker", "systemd") and config.mercure.process_runner != "nomad":
            logger.info("Docker processing complete")
            # Copy the task to the output folder (in case the module didn't move it)
            push_input_task(folder / "in", folder / "out")
            # If configured in the rule, copy the input images to the output folder
            if task is not None and task.process and (task.process[0] if isinstance(task.process,list) else task.process).retain_input_images == True:
                push_input_images(task_id, folder / "in", folder / "out")
            # Remember the number of DCM files in the output folder (for logging purpose)
            file_count_complete = len(list((folder / "out").glob(mercure_names.DCMFILTER)))

            # Push the results either to the success or error folder
            move_results(task_id, folder, lock, processing_success, needs_dispatching)
            shutil.rmtree(folder, ignore_errors=True)

            if processing_success:
                monitor.send_task_event(
                    monitor.task_event.PROCESS_COMPLETE, task_id, file_count_complete, "", "Processing job complete"
                )
                
                # If dispatching not needed, then trigger the completion notification (for docker/systemd)
                if not needs_dispatching:
                    monitor.send_task_event(monitor.task_event.COMPLETE, task_id, 0, "", "Task complete")
                    # TODO: task really is never none if processing_success is true

                    request_do_send = False
                    if outputs and task and (applied_rule :=config.mercure.rules.get(task.info.get("applied_rule"))) and applied_rule.notification_trigger_completion_on_request:
                        if notification.get_task_requested_notification(task):
                            request_do_send = True
                    trigger_notification(task, mercure_events.COMPLETED, notification.get_task_custom_notification(task), request_do_send)  # type: ignore
            else:
                monitor.send_task_event(monitor.task_event.ERROR, task_id, 0, "", "Processing failed")
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

def handle_processor_output(task:Task, task_processing:TaskProcessing, index:int, folder:Path) -> Any:
    output_file = folder / "out" / "result.json"
    if not output_file.is_file():
        logger.info("No result.json")
        return
    try:
        output = json.loads(output_file.read_text())
    except json.JSONDecodeError as e: 
        # Not json
        logger.info("Failed to parse result.json")
        return
    logger.info("Read result.json:")
    logger.info(output)
    monitor.send_processor_output(task, task_processing, index, output)
    return output

def move_results(
    task_id: str, folder: Path, lock: Optional[helper.FileLock], processing_success: bool, needs_dispatching: bool
) -> None:
    # Create a new lock file to ensure that no other process picks up the folder while copying
    logger.debug(f"Moving results folder {folder} {'with' if needs_dispatching else 'without'} dispatching")
    lock_file = folder / mercure_names.LOCK
    if lock_file.exists():
        logger.error(f"Folder already contains lockfile {folder}/" + mercure_names.LOCK)
        return
    try:
        lock_file.touch(exist_ok=False)
    except Exception:
        logger.error(f"Error locking folder to be moved {folder}", task_id)  # handle_error
        return

    if lock is not None:
        lock.free()
    if not processing_success:
        logger.debug(f"Failing: {folder}")
        move_out_folder(task_id, folder, Path(config.mercure.error_folder), move_all=True)
    else:
        if needs_dispatching:
            logger.debug(f"Dispatching: {folder}")
            move_out_folder(task_id, folder, Path(config.mercure.outgoing_folder))
        else:
            logger.debug(f"Success: {folder}")
            move_out_folder(task_id, folder, Path(config.mercure.success_folder))


def move_out_folder(task_id: str, source_folder: Path, destination_folder: Path, move_all=False) -> None:
    # source_folder = Path(source_folder_str)
    # destination_folder = Path(destination_folder_str)

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


def trigger_notification(task: Task, event: mercure_events, details: str="", send_always = False) -> None:
    current_rule_name = task.info.get("applied_rule")
    logger.debug(f"Notification {event.name}")
    # Check if the rule is available
    if not current_rule_name:
        logger.error(f"Missing applied_rule in task file in task {task.id}", task.id)  # handle_error
        return

    notification.trigger_notification_for_rule(
        current_rule_name,
        task.id,
        event,
        task=task,
        details=details,
        send_always=send_always,
    )
