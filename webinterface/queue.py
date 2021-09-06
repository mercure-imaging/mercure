"""
queue.py
========
Queue page for the graphical user interface of mercure.
"""

# Standard python includes
import os
from pathlib import Path

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
from common.constants import mercure_defs, mercure_names
from webinterface.common import get_user_information
from webinterface.common import templates


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
    job_list["1234-1234-1234-1234"] = {"Module": "Test", "ACC": "ACC1234", "MRN": "MRN1234", "Status": "Processing"}
    job_list["1334-1244-2234-1233"] = {
        "Module": "Anonymizer",
        "ACC": "ACC1234",
        "MRN": "MRN1234",
        "Status": "Scheduled",
    }
    job_list["4234-1234-1434-1234"] = {
        "Module": "Anonymizer",
        "ACC": "ACC1234",
        "MRN": "MRN1234",
        "Status": "Scheduled",
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
