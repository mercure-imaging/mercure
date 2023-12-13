"""
modules.py
==========
Modules page for the graphical user interface of mercure.
"""

# Standard python includes
import json
from typing import Dict

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, RedirectResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
import common.helper as helper
from common.constants import mercure_defs
from common.types import Module

from webinterface.common import get_user_information
from webinterface.common import templates

import docker

from decoRouter import Router as decoRouter
router = decoRouter()
logger = config.get_logger()


###################################################################################
## Common functions
###################################################################################


async def save_module(form, name) -> Response:
    """Save the settings for the module with the given name."""

    # Ensure that the module settings are valid. Should happen on the client side too, but can't hurt to check again.
    try:
        new_settings: Dict = json.loads(form.get("settings", "{}"))
    except:
        new_settings = {}

    config.mercure.modules[name] = Module(
        docker_tag=form.get("docker_tag", ""),
        additional_volumes=form.get("additional_volumes", ""),
        environment=form.get("environment", ""),
        docker_arguments=form.get("docker_arguments", ""),
        settings=new_settings,
        contact=form.get("contact", ""),
        comment=form.get("comment", ""),
        constraints=form.get("constraints", ""),
        resources=form.get("resources", ""),
        requires_root=form.get("requires_root",False) or form.get("container_type","mercure") == "monai"
    )
    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    return RedirectResponse(url="/modules/", status_code=303)


###################################################################################
## Modules endpoints
###################################################################################



@router.get("/")
@requires("authenticated", redirect="login")
async def show_modules(request):
    """Shows all installed modules"""

    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    used_modules = {}
    for rule in config.mercure.rules:
        used_module = config.mercure.rules[rule].get("processing_module", "NONE")
        if isinstance(used_module,list):
            for m in used_module:
                used_modules[m] = rule
        else:
            used_modules[used_module] = rule

    template = "modules.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "modules",
        "modules": config.mercure.modules,
        "used_modules": used_modules,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/")
@requires(["authenticated", "admin"], redirect="login")
async def add_module(request):
    """Creates a new module and forwards the user to the module edit page."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())
    name = form.get("name", "")

    if "/" in name:
        return PlainTextResponse("Invalid module name provided.")

    if name in config.mercure.modules:
        return PlainTextResponse("A module with this name already exists.")

    client = docker.from_env() # type: ignore
    try:
        client.images.get(form["docker_tag"])
    except docker.errors.ImageNotFound: 
        try:
            client.images.get_registry_data(form["docker_tag"])
        except:
            return PlainTextResponse(f"A Docker container with this tag does not exist locally or in the Docker Hub registry.")

    if form["container_type"] == "monai" and config.mercure.support_root_modules != True:
        return PlainTextResponse(f"MONAI modules must run as root user, but the setting 'Support Root Modules' is disabled in the mercure configuration. Enable it on the Configuration page before installing MONAI modules.")
    # logger.info(f'Created rule {name}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, name)

    await save_module(form, name)
    return PlainTextResponse(headers={"HX-Refresh":"true"})


@router.get("/edit/{module}")
@requires("authenticated", redirect="login")
async def edit_module(request):
    """Show the module edit page for the given module name."""
    module = request.path_params["module"]
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    settings_string = ""
    if config.mercure.modules[module].settings:
        settings_string = json.dumps(config.mercure.modules[module].settings, indent=4, sort_keys=False)

    runtime = helper.get_runner()

    template = "modules_edit.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "modules",
        "module": config.mercure.modules[module],
        "module_name": module,
        "settings": settings_string,
        "runtime": runtime,
        "support_root_modules": config.mercure.support_root_modules
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/edit/{module}")
@requires(["authenticated", "admin"], redirect="login")
async def edit_module_POST(request):
    """Save the settings for the given module name."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    name = request.path_params["module"]
    if name not in config.mercure.modules:
        return PlainTextResponse("Invalid module name - perhaps it was deleted?")

    return await save_module(form, name)


@router.post("/delete/{module}")
@requires(["authenticated", "admin"], redirect="login")
async def delete_module(request):
    """Deletes the module with the given module name."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    name = request.path_params["module"]
    if name in config.mercure.modules:
        del config.mercure.modules[name]

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")
    # logger.info(f'Created rule {newrule}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)
    return RedirectResponse(url="/modules", status_code=303)

modules_app = Starlette(routes=router)