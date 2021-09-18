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


logger = daiquiri.getLogger("queue")


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
                    if task.info.uid_type=="series":
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

            job_list[entry.name] = {
                "Module": job_module,
                "ACC": job_acc,
                "MRN": job_mrn,
                "Status": job_status,
                "Scope": job_scope,
            }

    return JSONResponse(job_list)


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
            job_target = ""
            job_acc = ""
            job_mrn = ""
            job_scope = "Series"
            job_status = "Queued"

            task_file = Path(entry.path) / mercure_names.TASKFILE

            try:
                with open(task_file, "r") as f:
                    task: Task = Task(**json.load(f))
                    if task.dispatch and task.dispatch.target_name:
                        job_target = task.dispatch.target_name
                    job_acc = task.info.acc
                    job_mrn = task.info.mrn
                    if task.info.uid_type=="series":
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

            job_list[entry.name] = {
                "Target": job_target,
                "ACC": job_acc,
                "MRN": job_mrn,
                "Status": job_status,
                "Scope": job_scope,
            }

    return JSONResponse(job_list)


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
                    job_acc = task.info.acc
                    job_mrn = task.info.mrn
                    # TODO: Fetch missing values
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

    processing_status = "Idle"
    routing_status = "Idle"

    if processing_suspended:
        processing_status = "Halted"

    if routing_suspended:
        routing_status = "Halted"

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
