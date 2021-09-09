"""
targets.py
==========
Targets page for the graphical user interface of mercure.
"""

# Standard python includes
import logging
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
from common.types import Target
from webinterface.common import *


daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("targets")


###################################################################################
## Targets endpoints
###################################################################################


targets_app = Starlette()


@targets_app.route("/", methods=["GET"])
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
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@targets_app.route("/", methods=["POST"])
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

    config.mercure.targets[newtarget] = Target(ip="", port="")

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Created target {newtarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_CREATE, request.user.display_name, newtarget)
    return RedirectResponse(url="/targets/edit/" + newtarget, status_code=303)


@targets_app.route("/edit/{target}", methods=["GET"])
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
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@targets_app.route("/edit/{target}", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def targets_edit_post(request) -> Union[RedirectResponse, PlainTextResponse]:
    """Updates the given target using the form values posted with the request."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edittarget = request.path_params["target"]
    form = dict(await request.form())

    if not edittarget in config.mercure.targets:
        return PlainTextResponse("Target does not exist anymore.")

    config.mercure.targets[edittarget].ip = form["ip"]
    config.mercure.targets[edittarget].port = form["port"]
    config.mercure.targets[edittarget].aet_target = form["aet_target"]
    config.mercure.targets[edittarget].aet_source = form["aet_source"]
    config.mercure.targets[edittarget].contact = form["contact"]
    config.mercure.targets[edittarget].comment = form["comment"]

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Edited target {edittarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_EDIT, request.user.display_name, edittarget)
    return RedirectResponse(url="/targets", status_code=303)


@targets_app.route("/delete/{target}", methods=["POST"])
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


@targets_app.route("/test/{target}", methods=["POST"])
@requires(["authenticated"], redirect="login")
async def targets_test_post(request) -> Response:
    """Tests the connectivity of the given target by executing ping and c-echo requests."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    testtarget = request.path_params["target"]

    ping_response = "False"
    cecho_response = "False"
    # target_ip = ""
    # target_port = ""
    # target_aec = "ANY-SCP"
    # target_aet = "ECHOSCU"

    target_ip = config.mercure.targets[testtarget].ip or ""
    target_port = config.mercure.targets[testtarget].port or ""
    target_aec = config.mercure.targets[testtarget].aet_target or "ANY-SCP"
    target_aet = config.mercure.targets[testtarget].aet_source or "ECHOSCU"

    logger.info(f"Testing target {testtarget}")

    if target_ip and target_port:
        if (await async_run("ping -w 1 -c 1 " + target_ip))[0] == 0:
            ping_response = "True"
            # Only test for c-echo if the ping was successful
            if (
                await async_run(
                    "echoscu -to 10 -aec " + target_aec + " -aet " + target_aet + " " + target_ip + " " + target_port
                )
            )[0] == 0:
                cecho_response = "True"

    return JSONResponse('{"ping": "' + ping_response + '", "c-echo": "' + cecho_response + '" }')
