"""
rules.py
========
Rules page for the graphical user interface of mercure.
"""

import json
# Standard python includes
import re
from typing import Any, Dict, Set

import common.config as config
import common.monitor as monitor
import common.rule_evaluation as rule_evaluation
import common.tagslist as tagslist
from common.tags_rule_interface import TagNotFoundException
from common.types import Rule
from decoRouter import Router as decoRouter
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from webinterface.common import strip_untrusted, templates
from webinterface.modules import BadRequestResponse

router = decoRouter()


logger = config.get_logger()


###################################################################################
# Rules endpoints
###################################################################################

@router.get("/")
@requires("authenticated", redirect="login")
async def rules(request) -> Response:
    """Show all defined routing rules. Can be executed by all logged-in users."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    template = "rules.html"
    context = {
        "request": request,
        "page": "rules",
        "rules": config.mercure.rules,
    }
    return templates.TemplateResponse(template, context)


@router.post("/duplicate")
@requires(["authenticated", "admin"], redirect="login")
async def duplicate_rule(request) -> Response:
    """Duplicates an existing routing rule."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")
    form = await request.form()
    new_name = form.get("new_name", "")
    if not re.fullmatch("[0-9a-zA-Z_\-]+", new_name):
        return BadRequestResponse("Invalid rule name provided")

    old_name = form.get("old_name", "")
    if not old_name or not new_name or old_name == new_name or new_name in config.mercure.rules:
        return PlainTextResponse("Invalid input or duplicate name.")

    config.mercure.rules[new_name] = Rule(**config.mercure.rules[old_name].__dict__)

    # return RedirectResponse(url="/rules", status_code=303)
    return RedirectResponse(url="/rules/edit/" + new_name, status_code=303)


@router.post("/")
@requires(["authenticated", "admin"], redirect="login")
async def add_rule(request) -> Response:
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    newrule = form.get("name", "")
    if not re.fullmatch("[0-9a-zA-Z_\-]+", newrule):
        return BadRequestResponse("Invalid rule name provided")

    if newrule in config.mercure.rules:
        return PlainTextResponse("Rule already exists.")

    default_payload_body = """Rule "{{ rule }}" triggered {{ event }}
{% if details is defined and details|length %}
Details:
{{ details }}
{% endif %}"""
    default_email_body = """Rule "{{ rule }}" triggered {{ event }}
Name: {{ patient_name }}
ACC: {{ acc }}
MRN: {{ mrn }}
{% if details is defined and details|length %}
Details:
{{ details }}
{% endif %}"""
    config.mercure.rules[newrule] = Rule(rule="False",
                                         notification_payload_body=default_payload_body,
                                         notification_email_body=default_email_body)

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Created rule {newrule}")
    monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)
    return RedirectResponse(url="/rules/edit/" + newrule, status_code=303)


@router.get("/edit/{rule}")
@requires(["authenticated", "admin"], redirect="login")
async def rules_edit(request) -> Response:
    """Shows the edit page for the given routing rule."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    rule = request.path_params["rule"]
    if rule not in config.mercure.rules:
        return PlainTextResponse("Rule does not exist anymore.")

    settings_string = ""
    if config.mercure.rules[rule].processing_settings:
        settings_string = json.dumps(config.mercure.rules[rule].processing_settings, indent=4, sort_keys=False)

    context = {
        "request": request,
        "page": "rules",
        "rules": config.mercure.rules,
        "targets": [t for t in config.mercure.targets if config.mercure.targets[t].direction in ("push", "both")],
        "modules": config.mercure.modules,
        "rule": rule,
        "alltags": tagslist.alltags,
        "sortedtags": tagslist.sortedtags,
        "processing_settings": settings_string,
        "process_runner": config.mercure.process_runner,
        "phi_notifications": config.mercure.phi_notifications,
    }

    template = "rules_edit.html"
    return templates.TemplateResponse(template, context)


@router.post("/edit/{rule}")
@requires(["authenticated", "admin"], redirect="login")
async def rules_edit_post(request) -> Response:
    """Updates the settings for the given routing rule."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    editrule = request.path_params["rule"]

    if editrule not in config.mercure.rules:
        return PlainTextResponse("Rule does not exist anymore.")
    try:
        form_data = await request.form()
        form = dict(form_data)
        target_list = form_data.getlist("target")
    except Exception:
        return PlainTextResponse("Invalid form data.")

    if not re.fullmatch("[^<\n]+|", form.get("tags", "")):
        return PlainTextResponse("Invalid tag name provided")

    # Ensure that the processing settings are valid. Should happen on the client side too, but can't hurt
    # to check again
    try:
        new_processing_settings: Dict = json.loads(form.get("processing_settings", "{}"))
    except Exception:
        new_processing_settings = {}

    if "processing_module_list" in form:
        processing_module = form.get("processing_module_list", "").split(",")
        if processing_module == [""]:
            processing_module = ""
    else:
        processing_module = form.get("processing_module", "")

    notification_payload = form.get("notification_payload", "")
    notification_payload = notification_payload.strip().lstrip("{").rstrip("}")

    new_rule: Rule = Rule(
        rule=form.get("rule", "False"),
        target=target_list,
        disabled=form.get("status_disabled", "False"),
        fallback=form.get("status_fallback", "False"),
        contact=form.get("contact", ""),
        comment=form.get("comment", ""),
        tags=strip_untrusted(form.get("tags", "")),
        action=form.get("action", "route"),
        action_trigger=form.get("action_trigger", "series"),
        study_trigger_condition=form.get("study_trigger_condition", "timeout"),
        study_trigger_series=form.get("study_trigger_series", ""),
        study_force_completion_action=form.get("study_force_completion_action", ""),
        priority=form.get("priority", "normal"),
        processing_module=processing_module,
        processing_settings=new_processing_settings,
        processing_retain_images=form.get("processing_retain_images", "False"),
        notification_webhook=form.get("notification_webhook", ""),
        notification_email=form.get("notification_email", ""),
        notification_payload=notification_payload,
        notification_payload_body=form.get("notification_payload_body", ""),
        notification_email_body=form.get("notification_email_body", ""),
        notification_email_type="html" if form.get("notification_email_html", False) else "plain",
        notification_trigger_reception=form.get("notification_trigger_reception", "False"),
        notification_trigger_completion=form.get("notification_trigger_completion", "False"),
        notification_trigger_completion_on_request=form.get("notification_trigger_completion_on_request", "False"),
        notification_trigger_error=form.get("notification_trigger_error", "False"),
    )
    config.mercure.rules[editrule] = new_rule

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Edited rule {editrule}")
    monitor.send_webgui_event(monitor.w_events.RULE_EDIT, request.user.display_name, editrule)
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/delete/{rule}")
@requires(["authenticated", "admin"], redirect="login")
async def rules_delete_post(request) -> Response:
    """Deletes the given routing rule"""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    deleterule = request.path_params["rule"]

    if deleterule in config.mercure.rules:
        del config.mercure.rules[deleterule]

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Deleted rule {deleterule}")
    monitor.send_webgui_event(monitor.w_events.RULE_DELETE, request.user.display_name, deleterule)
    return RedirectResponse(url="/rules", status_code=303)


@router.post("/test")
@requires(["authenticated", "admin"], redirect="login")
async def rules_test(request) -> Response:
    """Evalutes if a given routing rule is valid. The rule and testing dictionary have to be passed as form parameters."""
    noresult: Set[Any] = set()
    attrs_accessed = set()
    try:
        form = dict(await request.form())
        testrule = form["rule"]
        testvalues = json.loads(form["testvalues"])
    except Exception:
        return PlainTextResponse(
            ('<span class="tag is-warning is-medium ruleresult">'
             '<i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid test values')
        )
    try:
        result, attrs_accessed = rule_evaluation.eval_rule(testrule, testvalues)

        if result:
            style = "success"
            icon = "thumbs-up"
            text = "Trigger"
            inline = result if result is not True else noresult
        else:
            style = "info"
            icon = "thumbs-down"
            text = "Reject"
            inline = result if result is not False else noresult

    except TagNotFoundException as e:
        style = "info"
        icon = "thumbs-down"
        text = "Reject"
        inline = e

    except Exception as e:
        style = "danger"
        icon = "bug"
        text = "Error"
        inline = e

    attrs_accessed_info = ("\n".join([f"{x} = \"{testvalues[x]}\"" for x in attrs_accessed])
                           if len(attrs_accessed) > 0 else None)

    _inline = repr(inline) if not isinstance(inline, Exception) else str(inline)
    return PlainTextResponse(f'<span class="tag is-{style} is-medium ruleresult"><i class="fas fa-{icon}"></i>&nbsp;{text}</span>'  # noqa: E501
                             + (f'<pre style="display:inline; margin-left: 1em">{_inline}</pre>'
                                if inline is not noresult else '')
                             + (f'<pre style="margin: 1em">Tags evaluated:\n{attrs_accessed_info}</pre>' if attrs_accessed_info else '')  # noqa: E501
                             )


@router.post("/test_completionseries")
@requires(["authenticated", "admin"], redirect="login")
async def rules_test_completionseries(request) -> Response:
    """Evalutes if a given value for the series list for study completion is valid."""
    try:
        form = dict(await request.form())
        test_series_list = form["study_trigger_series"]
    except Exception:
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

rules_app = Starlette(routes=router)
