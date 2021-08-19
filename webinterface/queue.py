import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from starlette.authentication import requires
from starlette.authentication import (
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
    UnauthenticatedUser,
    AuthCredentials,
)
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.config import Config
from starlette.datastructures import URL, Secret
from starlette.routing import Route, Router

import common.helper as helper
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs, mercure_names
from webinterface.common import get_user_information
from webinterface.common import templates


queue_app = Starlette()

###################################################################################
## Queue endpoints
###################################################################################


@queue_app.route("/", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_queues(request):
    """Shows all installed modules"""

    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    processing_suspended = False
    processing_halt_file = Path(config.mercure["processing_folder"] + "/" + mercure_names.HALT)
    if processing_halt_file.exists():
        processing_suspended = True

    routing_suspended = False
    routing_halt_file = Path(config.mercure["outgoing_folder"] + "/" + mercure_names.HALT)
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
    processing_halt_file = Path(config.mercure["processing_folder"] + "/" + mercure_names.HALT)
    if processing_halt_file.exists():
        processing_suspended = True

    routing_suspended = False
    routing_halt_file = Path(config.mercure["outgoing_folder"] + "/" + mercure_names.HALT)
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

    processing_halt_file = Path(config.mercure["processing_folder"] + "/" + mercure_names.HALT)
    routing_halt_file = Path(config.mercure["outgoing_folder"] + "/" + mercure_names.HALT)

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
