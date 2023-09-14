"""
targets.py
==========
Targets page for the graphical user interface of mercure.
"""

# Standard python includes
import json
import daiquiri
from typing import Union

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, JSONResponse, RedirectResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs
from common.types import DicomTarget, SftpTarget
from webinterface.common import *
import dispatch.target_types as target_types
from decoRouter import Router as decoRouter
router = decoRouter()

logger = config.get_logger()


###################################################################################
## Targets endpoints
###################################################################################



@router.get("/")
@requires("authenticated", redirect="login")
async def show_targets(request) -> Response:
    """Shows all configured targets."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    used_targets = {}
    for rule in config.mercure.rules:
        used_target = config.mercure.rules[rule].get("target", "NONE")
        used_targets[used_target] = rule

    template = "targets.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "targets",
        "targets": config.mercure.targets,
        "used_targets": used_targets,
        "get_target_handler": target_types.get_handler,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/")
@requires(["authenticated", "admin"], redirect="login")
async def add_target(request) -> Response:
    """Creates a new target."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    newtarget = form.get("name", "")
    if newtarget in config.mercure.targets:
        return PlainTextResponse("Target already exists.")

    config.mercure.targets[newtarget] = DicomTarget(ip="", port="", aet_target="")

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Created target {newtarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_CREATE, request.user.display_name, newtarget)
    return RedirectResponse(url="/targets/edit/" + newtarget, status_code=303)


@router.get("/edit/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_edit(request) -> Response:
    """Shows the edit page for the given target."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edittarget = request.path_params["target"]

    if not edittarget in config.mercure.targets:
        return RedirectResponse(url="/targets", status_code=303)

    template = "targets_edit.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "targets",
        "targets": config.mercure.targets,
        "edittarget": edittarget,
        "get_target_handler": target_types.get_handler,
        "target_types": target_types.target_types(),
        "target_names": [
            k.get_name()
            for k in target_types.target_types()
            if k.get_name() != "dummy" or config.mercure.features.get("dummy_target")
        ],
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/edit/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_edit_post(request) -> Union[RedirectResponse, PlainTextResponse]:
    """Updates the given target using the form values posted with the request."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edittarget: str = request.path_params["target"]
    form = dict(await request.form())

    if not edittarget in config.mercure.targets:
        return PlainTextResponse("Target does not exist anymore.")

    TargetType = target_types.type_from_name(form["target_type"])

    config.mercure.targets[edittarget] = target_types.get_handler(form["target_type"]).from_form(
        form, TargetType, config.mercure.targets[edittarget]
    )

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Edited target {edittarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_EDIT, request.user.display_name, edittarget)
    return RedirectResponse(url="/targets", status_code=303)


@router.post("/delete/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_delete_post(request) -> Response:
    """Deletes the given target."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    deletetarget = request.path_params["target"]

    if deletetarget in config.mercure.targets:
        del config.mercure.targets[deletetarget]

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Deleted target {deletetarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_DELETE, request.user.display_name, deletetarget)
    return RedirectResponse(url="/targets", status_code=303)


@router.post("/test/{target}")
@requires(["authenticated"], redirect="login")
async def targets_test_post(request) -> Response:
    """Tests the connectivity of the given target by executing ping and c-echo requests."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    testtarget = request.path_params["target"]
    target = config.mercure.targets[testtarget]

    handler = target_types.get_handler(target)
    result = await handler.test_connection(target, testtarget)
    return templates.TemplateResponse(handler.test_template, {"request": request, "result": result})


targets_app = Starlette(routes=router)
