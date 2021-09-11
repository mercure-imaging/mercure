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
from common.constants import mercure_defs
from common.types import Module
from webinterface.common import get_user_information
from webinterface.common import templates


###################################################################################
## Common functions
###################################################################################


async def save_module(form, name) -> Response:
    """We already read the config by this time"""

    # Ensure that the processing settings are valid. Should happen on the client side too, but can't hurt
    # to check again
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
        comment=form.get("comment", ""),
        constraints=form.get("constraints", ""),
        resources=form.get("resources", ""),
    )
    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    return RedirectResponse(url="/modules/", status_code=303)


###################################################################################
## Modules endpoints
###################################################################################


modules_app = Starlette()


@modules_app.route("/", methods=["GET"])
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


@modules_app.route("/", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def add_module(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    name = form.get("name", "")
    if name in config.mercure.modules:
        return PlainTextResponse("Name already exists.")

    # logger.info(f'Created rule {name}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, name)

    return await save_module(form, name)


@modules_app.route("/edit/{module}", methods=["GET"])
@requires("authenticated", redirect="login")
async def edit_module(request):
    """Shows all installed modules"""
    module = request.path_params["module"]
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    settings_string = ""
    if config.mercure.modules[module].settings:
        settings_string = json.dumps(config.mercure.modules[module].settings, indent=4, sort_keys=False)

    template = "modules_edit.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "modules",
        "module": config.mercure.modules[module],
        "module_name": module,
        "settings": settings_string,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@modules_app.route("/edit/{module}", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def edit_module_POST(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    name = request.path_params["module"]
    if name not in config.mercure.modules:
        return PlainTextResponse("Invalid module name - perhaps it was deleted?")

    return await save_module(form, name)


@modules_app.route("/delete/{module}", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def delete_module(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
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
