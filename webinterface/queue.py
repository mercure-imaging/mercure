"""
queue.py
========
Queue page for the graphical user interface of mercure.
"""

# Standard python includes
import os
from pathlib import Path
import json
import daiquiri
from typing import Dict
import collections

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
from common.constants import mercure_defs, mercure_names
from webinterface.common import get_user_information
from webinterface.common import templates
from common.types import Task


logger = config.get_logger()


###################################################################################
## Queue endpoints
###################################################################################


queue_app = Starlette()


@queue_app.route("/", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_queues(request):
    """Shows all installed modules"""

    try:
        config.read_config()
    except:
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
        "mercure_version": mercure_defs.VERSION,
        "page": "queue",
        "processing_suspended": processing_suspended,
        "routing_suspended": routing_suspended,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@queue_app.route("/jobs/processing", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_jobs_processing(request):
    try:
        config.read_config()
    except:
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
                with open(task_file, "r") as f:
                    task: Task = Task(**json.load(f))
                    if task.process and task.process.module_name:
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

    sorted_jobs = collections.OrderedDict(sorted(job_list.items(), key=lambda x: (x[1]["Status"], x[1]["Creation_Time"]), reverse=False))  # type: ignore
    return JSONResponse(sorted_jobs)


@queue_app.route("/jobs/routing", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_jobs_routing(request):
    try:
        config.read_config()
    except:
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
                with open(task_file, "r") as f:
                    task: Task = Task(**json.load(f))
                    if task.dispatch and task.dispatch.target_name:
                        job_target = task.dispatch.target_name
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

    sorted_jobs = collections.OrderedDict(sorted(job_list.items(), key=lambda x: (x[1]["Status"], x[1]["Creation_Time"]), reverse=False))  # type: ignore
    return JSONResponse(sorted_jobs)


@queue_app.route("/jobs/studies", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_jobs_studies(request):
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_list = {}
    for entry in os.scandir(config.mercure.studies_folder):
        if entry.is_dir():
            job_uid = ""
            job_rule = ""
            job_acc = ""
            job_mrn = ""
            job_completion = "Timeout"
            job_created = ""
            job_series = 0

            task_file = Path(entry.path) / mercure_names.TASKFILE

            try:
                with open(task_file, "r") as f:
                    task: Task = Task(**json.load(f))
                    if (not task.study) or (not task.info):
                        raise Exception()
                    job_uid = task.info.uid
                    if task.info.applied_rule:
                        job_rule = task.info.applied_rule
                    job_acc = task.info.acc
                    job_mrn = task.info.mrn
                    if task.study.complete_force == "True":
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


@queue_app.route("/jobs/fail", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_jobs_fail(request):
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_list: Dict = {}

    for entry in os.scandir(config.mercure.error_folder):
        if entry.is_dir():
            job_name: str = entry.name
            job_acc: str = ""
            job_mrn: str = ""
            job_scope: str = "Series"
            job_failstage: str = "Unknown"

            task_file = Path(entry.path) / mercure_names.TASKFILE
            if not task_file.exists():
                task_file = Path(entry.path) / "in" / mercure_names.TASKFILE

            try:
                with open(task_file, "r") as f:
                    task: Task = Task(**json.load(f))
                    job_acc = task.info.acc
                    job_mrn = task.info.mrn
                    if task.info.uid_type == "series":
                        job_scope = "Series"
                    else:
                        job_scope = "Study"
            except Exception as e:
                logger.exception(e)
                job_acc = "Error"
                job_mrn = "Error"
                job_scope = "Error"

            job_list[job_name] = {
                "ACC": job_acc,
                "MRN": job_mrn,
                "Scope": job_scope,
                "FailStage": job_failstage,
            }

    return JSONResponse(job_list)


@queue_app.route("/status", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_queues_status(request):

    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_suspended = False
    processing_halt_file = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)
    if processing_halt_file.exists():
        processing_suspended = True

    routing_suspended = False
    routing_halt_file = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)
    if routing_halt_file.exists():
        routing_suspended = True

    processing_active = False
    for entry in os.scandir(config.mercure.processing_folder):
        if entry.is_dir():
            processing_file = Path(entry.path) / mercure_names.PROCESSING
            if processing_file.exists():
                processing_active = True
                break

    routing_actvie = False
    for entry in os.scandir(config.mercure.outgoing_folder):
        if entry.is_dir():
            processing_file = Path(entry.path) / mercure_names.PROCESSING
            if processing_file.exists():
                routing_actvie = True
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
        if routing_actvie:
            routing_status = "Suspending"
        else:
            routing_status = "Halted"
    else:
        if routing_actvie:
            routing_status = "Processing"

    queue_status = {
        "processing_status": processing_status,
        "processing_suspended": str(processing_suspended),
        "routing_status": routing_status,
        "routing_suspended": str(routing_suspended),
    }

    return JSONResponse(queue_status)


@queue_app.route("/status", methods=["POST"])
@requires("authenticated", redirect="login")
async def set_queues_status(request):

    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_halt_file = Path(config.mercure.processing_folder + "/" + mercure_names.HALT)
    routing_halt_file = Path(config.mercure.outgoing_folder + "/" + mercure_names.HALT)

    form = dict(await request.form())
    print(form)

    try:
        if form.get("suspend_processing", "false") == "true":
            processing_halt_file.touch()
        else:
            processing_halt_file.unlink()
    except:
        pass

    try:
        if form.get("suspend_routing", "false") == "true":
            routing_halt_file.touch()
        else:
            routing_halt_file.unlink()
    except:
        pass

    return JSONResponse({"result": "OK"})


@queue_app.route("/jobinfo/{category}/{id}", methods=["GET"])
@requires("authenticated", redirect="login")
async def get_jobinfo(request):
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    job_category = request.path_params["category"]
    job_id = request.path_params["id"]
    job_pathstr: str = ""

    if job_category == "processing":
        job_pathstr = config.mercure.processing_folder + "/" + job_id
    elif job_category == "routing":
        job_pathstr = config.mercure.outgoing_folder + "/" + job_id
    elif job_category == "studies":
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
