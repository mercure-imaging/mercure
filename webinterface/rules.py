"""
rules.py
========
Rules page for the graphical user interface of mercure.
"""

# Standard python includes
import logging
import daiquiri
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union, List
import json


# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, Response
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

# App-specific includes
import common.helper as helper
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs
from common.types import Module
from common.types import Rule
import common.rule_evaluation as rule_evaluation
from webinterface.common import *
import webinterface.tagslist as tagslist


daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("targets")


###################################################################################
## Rules endpoints
###################################################################################


rules_app = Starlette()


@rules_app.route("/", methods=["GET"])
@requires("authenticated", redirect="login")
async def show_rules(request) -> Response:
    """Show all defined routing rules. Can be executed by all logged-in users."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    template = "rules.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "rules",
        "rules": config.mercure.rules,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@rules_app.route("/", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def add_rule(request) -> Response:
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    newrule = form.get("name", "")
    if newrule in config.mercure.rules:
        return PlainTextResponse("Rule already exists.")

    config.mercure.rules[newrule] = Rule(rule="False")

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Created rule {newrule}")
    monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)
    return RedirectResponse(url="/rules/edit/" + newrule, status_code=303)


@rules_app.route("/edit/{rule}", methods=["GET"])
@requires(["authenticated", "admin"], redirect="login")
async def rules_edit(request) -> Response:
    """Shows the edit page for the given routing rule."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    rule = request.path_params["rule"]
    template = "rules_edit.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "rules",
        "rules": config.mercure.rules,
        "targets": config.mercure.targets,
        "modules": config.mercure.modules,
        "rule": rule,
        "alltags": tagslist.alltags,
        "sortedtags": tagslist.sortedtags,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@rules_app.route("/edit/{rule}", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def rules_edit_post(request) -> Response:
    """Updates the settings for the given routing rule."""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    editrule = request.path_params["rule"]
    form = dict(await request.form())

    if not editrule in config.mercure.rules:
        return PlainTextResponse("Rule does not exist anymore.")

    new_rule: Rule = Rule(
        rule=form.get("rule", "False"),
        target=form.get("target", ""),
        disabled=form.get("status_disabled", "False"),
        fallback=form.get("status_fallback", "False"),
        contact=form.get("contact", ""),
        comment=form.get("comment", ""),
        tags=form.get("tags", ""),
        action=form.get("action", "route"),
        action_trigger=form.get("action_trigger", "series"),
        study_trigger_condition=form.get("study_trigger_condition", "timeout"),
        study_trigger_series=form.get("study_trigger_series", ""),
        priority=form.get("priority", "normal"),
        processing_module=form.get("processing_module", ""),
        processing_settings=form.get("processing_settings", ""),
        notification_webhook=form.get("notification_webhook", ""),
        notification_payload=form.get("notification_payload", ""),
        notification_trigger_reception=form.get("notification_trigger_reception", "False"),
        notification_trigger_completion=form.get("notification_trigger_completion", "False"),
        notification_trigger_error=form.get("notification_trigger_error", "False"),
    )
    config.mercure.rules[editrule] = new_rule

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Edited rule {editrule}")
    monitor.send_webgui_event(monitor.w_events.RULE_EDIT, request.user.display_name, editrule)
    return RedirectResponse(url="/rules", status_code=303)


@rules_app.route("/delete/{rule}", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def rules_delete_post(request) -> Response:
    """Deletes the given routing rule"""
    try:
        config.read_config()
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    deleterule = request.path_params["rule"]

    if deleterule in config.mercure.rules:
        del config.mercure.rules[deleterule]

    try:
        config.save_config()
    except:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Deleted rule {deleterule}")
    monitor.send_webgui_event(monitor.w_events.RULE_DELETE, request.user.display_name, deleterule)
    return RedirectResponse(url="/rules", status_code=303)


@rules_app.route("/test", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def rules_test(request) -> Response:
    """Evalutes if a given routing rule is valid. The rule and testing dictionary have to be passed as form parameters."""
    try:
        form = dict(await request.form())
        testrule = form["rule"]
        testvalues = json.loads(form["testvalues"])
    except:
        return PlainTextResponse(
            '<span class="tag is-warning is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid test values'
        )

    result = rule_evaluation.test_rule(testrule, testvalues)

    if result == "True":
        return PlainTextResponse(
            '<span class="tag is-success is-medium ruleresult"><i class="fas fa-thumbs-up"></i>&nbsp;Route</span>'
        )
    else:
        if result == "False":
            return PlainTextResponse(
                '<span class="tag is-info is-medium ruleresult"><i class="fas fa-thumbs-down"></i>&nbsp;Discard</span>'
            )
        else:
            return PlainTextResponse(
                '<span class="tag is-danger is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid rule: '
                + result
            )


@rules_app.route("/test_completionseries", methods=["POST"])
@requires(["authenticated", "admin"], redirect="login")
async def rules_test_completionseries(request) -> Response:
    """Evalutes if a given value for the series list for study completion is valid."""
    try:
        form = dict(await request.form())
        test_series_list = form["study_trigger_series"]
    except:
        return PlainTextResponse(
            '<span class="tag is-warning is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid'
        )

    result = rule_evaluation.test_completion_series(test_series_list)

    if result == "True":
        return PlainTextResponse('<i class="fas fa-check-circle fa-lg has-text-success"></i>&nbsp;&nbsp;Valid')
    else:
        return PlainTextResponse(
            '<i class="fas fa-times-circle fa-lg has-text-danger"></i>&nbsp;&nbsp;Invalid: ' + result
        )
