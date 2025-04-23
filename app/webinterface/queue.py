"""
queue.py
========
Queue page for the graphical user interface of mercure.
"""

import collections
import json
import os
import shutil
import time
# Standard python includes
from enum import Enum
from pathlib import Path
from typing import Dict, cast

import common.config as config
import common.monitor as monitor
import routing.generate_taskfile as generate_taskfile
from common.constants import mercure_actions, mercure_names
# App-specific includes
from common.event_types import FailStage
# App-specific includes
from common.helper import FileLock
from common.types import EmptyDict, Task
from decoRouter import Router as decoRouter
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.responses import JSONResponse, PlainTextResponse
from webinterface.common import templates

router = decoRouter()

logger = config.get_logger()


class RestartTaskErrors(str, Enum):
    TASK_NOT_READY = "not_ready"
    NO_TASK_FILE = "no_task_file"
    WRONG_JOB_TYPE = "wrong_type"
    NO_DISPATCH_STATUS = "no_dispatch_status"
    NO_AS_RECEIVED = "no_as_received"
    CURRENTLY_PROCESSING = "currently_processing"
    NO_RULE_APPLIED = "no_rule_applied"
    FAILED_TO_ADD_PROCESSING = "failed_to_add_processing"

###################################################################################
# Queue endpoints
###################################################################################


@router.get("/")
@requires("authenticated", redirect="login")
async def show_queues(request):
    """Shows all installed modules"""

    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_suspended = False
    processing_halt_file = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)
    if processing_halt_file.exists():
        processing_suspended = True

    routing_suspended = False
    routing_halt_file = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)
    if routing_halt_file.exists():
        routing_suspended = True

    template = "queue.html"
    context = {
        "request": request,
        "page": "queue",
        "processing_suspended": processing_suspended,
        "routing_suspended": routing_suspended,
    }
    return templates.TemplateResponse(template, context)


@router.get("/jobs/processing")
@requires("authenticated", redirect="login")
async def show_jobs_processing(request):
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    # TODO: Order by time

    job_list = {}
    for entry in os.scandir(config.mercure.processing_folder):
        if entry.is_dir():
            job_module = ""
            job_acc = ""
            job_mrn = ""
            job_scope = "Series"
            job_status = "Queued"

            processing_file = Path(entry.path) / mercure_names.PROCESSING
            task_file = Path(entry.path) / mercure_names.TASKFILE
            if processing_file.exists():
                job_status = "Processing"
                task_file = Path(entry.path) / "in" / mercure_names.TASKFILE
            else:
                pass

            try:
                task = Task.from_file(task_file)
                if task.process:
                    if isinstance(task.process, list):
                        job_module = ", ".join([p.module_name for p in task.process])
                    else:
                        job_module = task.process.module_name
                job_acc = task.info.acc
                job_mrn = task.info.mrn
                if task.info.uid_type == "series":
                    job_scope = "Series"
                else:
                    job_scope = "Study"
            except Exception as e:
                logger.exception(e)
                job_module = "Error"
                job_acc = "Error"
                job_mrn = "Error"
                job_scope = "Error"
                job_status = "Error"

            timestamp: float = entry.stat().st_mtime
            job_name: str = entry.name

            job_list[job_name] = {
                "Creation_Time": timestamp,
                "Module": job_module,
                "ACC": job_acc,
                "MRN": job_mrn,
                "Status": job_status,
                "Scope": job_scope,
            }

    sorted_jobs = collections.OrderedDict(sorted(job_list.items(),
                                                 key=lambda x: (x[1]["Status"], x[1]["Creation_Time"]),
                                                 reverse=False))  # type: ignore
    return JSONResponse(sorted_jobs)


@router.get("/jobs/routing")
@requires("authenticated", redirect="login")
async def show_jobs_routing(request):
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_list = {}
    for entry in os.scandir(config.mercure.outgoing_folder):
        if entry.is_dir():
            job_target: str = ""
            job_acc: str = ""
            job_mrn: str = ""
            job_scope: str = "Series"
            job_status: str = "Queued"

            processing_file = Path(entry.path) / mercure_names.PROCESSING
            if processing_file.exists():
                job_status = "Processing"

            task_file = Path(entry.path) / mercure_names.TASKFILE
            try:
                task = Task.from_file(task_file)
                if task.dispatch and task.dispatch.target_name:
                    if isinstance(task.dispatch.target_name, str):
                        job_target = task.dispatch.target_name
                    else:
                        job_target = ", ".join(task.dispatch.target_name)
                job_acc = task.info.acc
                job_mrn = task.info.mrn
                if task.info.uid_type == "series":
                    job_scope = "Series"
                else:
                    job_scope = "Study"
            except Exception as e:
                logger.exception(e)
                job_target = "Error"
                job_acc = "Error"
                job_mrn = "Error"
                job_scope = "Error"
                job_status = "Error"

            timestamp: float = entry.stat().st_mtime
            job_name: str = entry.name

            job_list[job_name] = {
                "Creation_Time": timestamp,
                "Target": job_target,
                "ACC": job_acc,
                "MRN": job_mrn,
                "Status": job_status,
                "Scope": job_scope,
            }

    sorted_jobs = collections.OrderedDict(sorted(job_list.items(),
                                                 key=lambda x: (x[1]["Status"], x[1]["Creation_Time"]),
                                                 reverse=False))  # type: ignore
    return JSONResponse(sorted_jobs)


@router.post("/jobs/studies/force-complete")
@requires("authenticated", redirect="login")
async def force_study_complete(request):
    params = dict(await request.form())
    job_id = params["id"]
    job_path: Path = Path(config.mercure.studies_folder) / job_id
    if not (job_path / mercure_names.TASKFILE).exists():
        return JSONResponse({"error": "no such study"}, 404)

    (job_path / mercure_names.FORCE_COMPLETE).touch()
    return JSONResponse({"success": True})


@router.get("/jobs/studies")
@requires("authenticated", redirect="login")
async def show_jobs_studies(request):
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_list = {}
    for entry in os.scandir(config.mercure.studies_folder):
        if not entry.is_dir():
            continue
        job_uid = ""
        job_rule = ""
        job_acc = ""
        job_mrn = ""
        job_completion = "Timeout"
        job_created = ""
        job_series = 0

        task_file = Path(entry.path) / mercure_names.TASKFILE

        try:
            task = Task.from_file(task_file)
            if (not task.study) or (not task.info):
                raise Exception("Task file does not contain study information")
            job_uid = task.info.uid
            if task.info.applied_rule:
                job_rule = task.info.applied_rule
            job_acc = task.info.acc
            job_mrn = task.info.mrn
            if task.study.complete_force is True:
                job_completion = "Force"
            else:
                if task.study.complete_trigger == "received_series":
                    job_completion = "Series"
            job_created = task.study.creation_time
            if task.study.received_series:
                job_series = len(task.study.received_series)
        except Exception as e:
            logger.exception(e)
            job_uid = "Error"
            job_rule = "Error"
            job_acc = "Error"
            job_mrn = "Error"
            job_completion = "Error"
            job_created = "Error"

        job_list[entry.name] = {
            "UID": job_uid,
            "Rule": job_rule,
            "ACC": job_acc,
            "MRN": job_mrn,
            "Completion": job_completion,
            "Created": job_created,
            "Series": job_series,
        }

    return JSONResponse(job_list)


@router.get("/jobs/fail")
@requires("authenticated", redirect="login")
async def show_jobs_fail(request):
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_list: Dict = {}

    for entry in os.scandir(config.mercure.error_folder):
        if not entry.is_dir():
            continue
        job_name: str = entry.name
        timestamp: float = entry.stat().st_mtime
        job_acc: str = ""
        job_mrn: str = ""
        job_scope: str = "Series"
        job_failstage: str = "Unknown"

        # keeping the manual way of getting the fail stage too for now
        try:
            job_failstage = get_fail_stage(Path(entry.path))
        except Exception as e:
            logger.exception(e)

        task_file = Path(entry.path) / mercure_names.TASKFILE
        if not task_file.exists():
            task_file = Path(entry.path) / "in" / mercure_names.TASKFILE

        try:
            task = Task.from_file(task_file)
            job_acc = task.info.acc
            job_mrn = task.info.mrn
            if task.info.uid_type == "series":
                job_scope = "Series"
            else:
                job_scope = "Study"
            if (task.info.fail_stage):
                job_failstage = str(task.info.fail_stage).capitalize()

        except Exception as e:
            logger.exception(e)
            job_acc = "Error"
            job_mrn = "Error"
            job_scope = "Error"

        job_list[job_name] = {
            "ACC": job_acc + "<b>foo</b>",
            "MRN": job_mrn,
            "Scope": job_scope,
            "FailStage": job_failstage,
            "CreationTime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
        }
    sorted_jobs = collections.OrderedDict(sorted(job_list.items(),  # type: ignore
                                                 key=lambda x: x[1]["CreationTime"],  # type: ignore
                                                 reverse=False))  # type: ignore
    return JSONResponse(sorted_jobs)


@router.get("/status")
@requires("authenticated", redirect="login")
async def show_queues_status(request):

    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_suspended = False
    processing_halt_file = Path(config.mercure.processing_folder) / mercure_names.HALT
    if processing_halt_file.exists():
        processing_suspended = True

    routing_suspended = False
    routing_halt_file = Path(config.mercure.outgoing_folder) / mercure_names.HALT
    if routing_halt_file.exists():
        routing_suspended = True

    processing_active = False
    for entry in os.scandir(config.mercure.processing_folder):
        if entry.is_dir():
            processing_file = Path(entry.path) / mercure_names.PROCESSING
            if processing_file.exists():
                processing_active = True
                break

    routing_active = False
    for entry in os.scandir(config.mercure.outgoing_folder):
        if entry.is_dir():
            processing_file = Path(entry.path) / mercure_names.PROCESSING
            if processing_file.exists():
                routing_active = True
                break

    processing_status = "Idle"
    if processing_suspended:
        if processing_active:
            processing_status = "Suspending"
        else:
            processing_status = "Halted"
    else:
        if processing_active:
            processing_status = "Processing"

    routing_status = "Idle"
    if routing_suspended:
        if routing_active:
            routing_status = "Suspending"
        else:
            routing_status = "Halted"
    else:
        if routing_active:
            routing_status = "Processing"

    queue_status = {
        "processing_status": processing_status,
        "processing_suspended": str(processing_suspended),
        "routing_status": routing_status,
        "routing_suspended": str(routing_suspended),
    }

    return JSONResponse(queue_status)


@router.post("/status")
@requires("authenticated", redirect="login")
async def set_queues_status(request):

    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_halt_file = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)
    routing_halt_file = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)

    try:
        form = dict(await request.form())
        if form.get("suspend_processing", "false") == "true":
            processing_halt_file.touch()
        else:
            processing_halt_file.unlink()
    except Exception:
        pass

    try:
        if form.get("suspend_routing", "false") == "true":
            routing_halt_file.touch()
        else:
            routing_halt_file.unlink()
    except Exception:
        pass

    return JSONResponse({"result": "OK"})


@router.post("/jobinfo/{category}/{id}")
@requires("authenticated", redirect="login")
async def get_jobinfo(request):
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_category = request.path_params["category"]
    job_id = request.path_params["id"]
    job_pathstr: str = ""

    if job_category == "processing":
        job_pathstr = config.mercure.processing_folder + "/" + job_id
    elif job_category == "routing":
        job_pathstr = config.mercure.outgoing_folder + "/" + job_id
    elif job_category == "studies":
        # Note: For studies, the job_id contains a dash character, which is removed from the URL. Thus,
        #       take the information from the request body instead.
        params = dict(await request.form())
        job_id = params["jobId"]
        job_pathstr = config.mercure.studies_folder + "/" + job_id
    elif job_category == "failure":
        job_pathstr = config.mercure.error_folder + "/" + job_id
    else:
        return PlainTextResponse("Invalid request")

    job_path = Path(job_pathstr + "/task.json")

    if (job_category == "processing") and (not job_path.exists()):
        job_path = Path(job_pathstr + "/in/task.json")

    if (job_category == "failure") and (not job_path.exists()):
        job_path = Path(job_pathstr + "/in/task.json")

    if job_path.exists():
        with open(job_path, "r") as json_file:
            loaded_task = json.load(json_file)
        loaded_task = json.dumps(loaded_task, indent=4, sort_keys=False)
        return JSONResponse(loaded_task)
    else:
        return PlainTextResponse("Task not found. Refresh view!")


@router.post("/jobs/fail/restart-job")
@requires("authenticated", redirect="login")
async def restart_job(request):
    """
    Restarts a failed job. This endpoint handles both dispatch and processing failures.
    """
    form = await request.form()
    if not (task_id := form.get("task_id")):
        return JSONResponse({"error": "No task ID provided"}, status_code=500)

    # First check if this is a failed task in the error folder
    task_folder = Path(config.mercure.error_folder) / task_id
    logger.info(f"Checking if error folder for task {task_id} exists: {task_folder}")
    if not task_folder.exists():
        logger.info(f"Error folder for task {task_id} does not exist")
        return JSONResponse({"error": "Task not found in error folder"}, status_code=404)
    if not (task_folder / "as_received").exists():
        return JSONResponse({"error": "No original files found for this task"}, status_code=404)

    # Check if this is a processing failure based on fail_stage
    task_file = task_folder / mercure_names.TASKFILE
    if not task_file.exists():
        task_file = task_folder / "in" / mercure_names.TASKFILE
    if not task_file.exists():
        task_file = task_folder / "as_received" / mercure_names.TASKFILE

    if not task_file.exists():
        logger.info(f"Task file {task_file} does not exist")
        return JSONResponse({"error": f"Task file {task_file} does not exist"}, status_code=404)

    logger.info(f"Task file for task {task_id} exists: {task_file}")
    try:
        task = Task.from_file(task_file)
        fail_stage = task.info.fail_stage

        if not fail_stage:
            logger.warning("No fail stage information found in the task file")
            return JSONResponse({"error": "No fail stage information found in the task file"}, status_code=400)

        # If fail_stage is "processing", restart as processing task
        if fail_stage == FailStage.PROCESSING:
            logger.info(f"Task {task_id} failed during processing, restarting as processing task")
            return JSONResponse(restart_processing_task(task_id, task_folder, is_error=True))
        # If fail_stage is "dispatching", restart as dispatch task
        elif fail_stage == FailStage.DISPATCHING:
            logger.info(f"Task {task_id} failed during dispatching, restarting as dispatch task")
            return JSONResponse(restart_dispatch(task_folder, Path(config.mercure.outgoing_folder)))
        else:
            logger.warning(f"Unknown fail stage: {fail_stage}")
            return JSONResponse({"error": f"Unknown fail stage {fail_stage}"}, status_code=400)
    except Exception as e:
        logger.exception(f"Error restarting task: {str(e)}")
        return JSONResponse({"error": f"Error restarting task: {str(e)}"}, status_code=500)


def restart_processing_task(task_id: str, source_folder: Path, is_error: bool = False) -> Dict:
    """
    Restarts a processing task by moving it from the source folder (error or success) to the processing folder.

    Args:
        task_id: The ID of the task to restart
        source_folder: Path to the task folder in the source directory (error or success)
        is_error: Whether the source folder is the error folder (True) or success folder (False)

    Returns:
        Dict with success or error information
    """

    # Find the task.json file
    task_file = source_folder / mercure_names.TASKFILE
    if not task_file.exists():
        task_file = source_folder / "in" / mercure_names.TASKFILE
    if not task_file.exists():
        task_file = source_folder / "as_received" / mercure_names.TASKFILE

    if not task_file.exists():
        return {"error": "No task file found", "error_code": RestartTaskErrors.NO_TASK_FILE}

    # Check if as_received folder exists
    as_received_folder = source_folder / "as_received"
    if not as_received_folder.exists():
        return {"error": "No original files found for this task", "error_code": RestartTaskErrors.NO_AS_RECEIVED}

    # Create a new folder in the processing directory
    processing_folder = Path(config.mercure.processing_folder) / task_id
    if processing_folder.exists():
        return {"error": "Task is currently being processed", "error_code": RestartTaskErrors.TASK_NOT_READY}

    # Create the processing folder structure
    try:
        processing_folder.mkdir(exist_ok=False)
    except:
        return {"error": "Could not create processing folder", "error_code": RestartTaskErrors.TASK_NOT_READY}

    try:
        try:
            lock = FileLock(processing_folder / mercure_names.LOCK)
        except:
            logger.exception(f"Could not create lock file for processing folder {processing_folder}")
            return {"error": "Could not create lock file for processing folder", "error_code": RestartTaskErrors.TASK_NOT_READY}

        # Copy the as_received files to the input folder
        for file_path in as_received_folder.glob("*"):
            if file_path.is_file():
                shutil.copy2(file_path, processing_folder / file_path.name)

        # Copy and update the task.json file
        task = Task.from_file(task_file)
        if not task.info.applied_rule:
            logger.error(f"Task {task.id} does not have an applied rule")
            return {"error": "Task does not have an applied rule", "error_code": RestartTaskErrors.NO_RULE_APPLIED}
        # Clear the fail_stage
        task.info.fail_stage = None
        if task.info.applied_rule is None:
            return {"error": "No rule provided"}
        if task.info.applied_rule not in config.mercure.rules.keys():
            return {"error": f"Rule '{task.info.applied_rule}' not found in {config.mercure.rules.keys()}"}
        if config.mercure.rules[task.info.applied_rule].action not in ("both", "process"):
            return {"error": "Invalid rule action: this rule currently does not perform processing."}
        try:
            task.process = generate_taskfile.add_processing(task.info.applied_rule) or (cast(EmptyDict, {}))
            # task.dispatching = generate_taskfile.add_dispatching(task_id, uid, task.info.applied_rule, target) or cast(EmptyDict, {}),
        except Exception as e:
            logger.exception("Failed to generate task file")
            return {"error": "Failed to generate task file"}

        if task.process is None:
            return {"error": f"Failed to generate task file: error in rule"}
        # Write the updated task file

        task.to_file(processing_folder / mercure_names.TASKFILE)
        logger.info(task.json())

        # Log the restart action
        source_type = "error" if is_error else "success"
        logger.info(f"Processing job {task_id} moved from {source_type} folder to processing folder")
        monitor.send_task_event(
            monitor.task_event.PROCESS_RESTART, task_id, 0, "", f"Processing job restarted from {source_type} folder"
        )
        try:
            shutil.rmtree(source_folder)
        except:
            logger.exception("Failed to remove source folder")
        lock.free()
        return {
            "success": True,
            "message": f"Processing job {task_id} has been moved from {source_type} folder to processing folder"
        }
    except:
        logger.exception("Failed to restart processing job")

        lock.free()
        try:
            shutil.rmtree(processing_folder)
        except:
            logger.error(f"Failed to remove processing folder {processing_folder}")

        return {"error": "Failed to restart task"}


def is_dispatch_failure(taskfile_folder: Path) -> bool:
    """
    Determines if a task in the error folder is a dispatch failure.
    """
    if not taskfile_folder.exists() or not (taskfile_folder / mercure_names.TASKFILE).exists():
        return False

    try:
        with open(taskfile_folder / mercure_names.TASKFILE, "r") as json_file:
            loaded_task = json.load(json_file)

        action = loaded_task.get("info", {}).get("action", "")
        if action and action in (mercure_actions.BOTH, mercure_actions.ROUTE):
            return True
    except Exception:
        pass

    return False


def restart_dispatch(taskfile_folder: Path, outgoing_folder: Path) -> dict:
    # For now, verify if only dispatching failed and previous steps were successful
    dispatch_ready = (
        not (taskfile_folder / mercure_names.LOCK).exists()
        and not (taskfile_folder / mercure_names.ERROR).exists()
        and not (taskfile_folder / mercure_names.PROCESSING).exists()
    )
    if not dispatch_ready:
        return {"error": "Task not ready for dispatching.", "error_code": RestartTaskErrors.TASK_NOT_READY}

    if not (taskfile_folder / mercure_names.TASKFILE).exists():
        return {"error": "Task file does not exist", "error_code": RestartTaskErrors.NO_TASK_FILE}

    taskfile_path = taskfile_folder / mercure_names.TASKFILE
    with open(taskfile_path, "r") as json_file:
        loaded_task = json.load(json_file)

    action = loaded_task.get("info", {}).get("action", "")
    if action and action not in (mercure_actions.BOTH, mercure_actions.ROUTE):
        return {"error": "Job not suitable for dispatching.", "error_code": RestartTaskErrors.WRONG_JOB_TYPE}

    task_id = taskfile_folder.name
    if "dispatch" in loaded_task and "status" in loaded_task["dispatch"]:
        (taskfile_folder / mercure_names.LOCK).touch()
        dispatch = loaded_task["dispatch"]
        dispatch["retries"] = None
        dispatch["next_retry_at"] = None

        # Clear fail_stage if it exists
        if "info" in loaded_task and "fail_stage" in loaded_task["info"]:
            loaded_task["info"]["fail_stage"] = None

        with open(taskfile_path, "w") as json_file:
            json.dump(loaded_task, json_file)
        # Dispatcher will skip the completed targets we just need to copy the case to the outgoing folder
        shutil.move(str(taskfile_folder), str(outgoing_folder))
        (Path(outgoing_folder) / task_id / mercure_names.LOCK).unlink()

    else:
        return {"error": "Could not check dispatch status of task file.", "error_code": RestartTaskErrors.NO_DISPATCH_STATUS}

    return {"success": "task restarted"}


def get_fail_stage(taskfile_folder: Path) -> str:
    if not taskfile_folder.exists():
        return "Unknown"

    dispatch_ready = (
        not (taskfile_folder / mercure_names.LOCK).exists()
        and not (taskfile_folder / mercure_names.ERROR).exists()
        and not (taskfile_folder / mercure_names.PROCESSING).exists()
    )

    if not dispatch_ready or not (taskfile_folder / mercure_names.TASKFILE).exists():
        return "Unknown"

    taskfile_path = taskfile_folder / mercure_names.TASKFILE
    with open(taskfile_path, "r") as json_file:
        loaded_task = json.load(json_file)

    action = loaded_task.get("info", {}).get("action", "")
    if action and action not in (mercure_actions.BOTH, mercure_actions.ROUTE):
        return "Unknown"

    return "Dispatching"


queue_app = Starlette(routes=router)
