"""
rules.py
========
Rules page for the graphical user interface of mercure.
"""

# Standard python includes
import daiquiri
from typing import Dict
import json

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, RedirectResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs
from common.tags_rule_interface import TagNotFoundException
from common.types import Rule
import common.rule_evaluation as rule_evaluation
import common.helper as helper
from webinterface.common import *
import common.tagslist as tagslist
from decoRouter import Router as decoRouter
router = decoRouter()


logger = config.get_logger()


###################################################################################
## Rules endpoints
###################################################################################

@router.get("/")
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


@router.post("/")
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
    config.mercure.rules[newrule] = Rule(rule="False",notification_payload_body=default_payload_body, notification_email_body=default_email_body)

    try:
        config.save_config()
    except:
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
    except:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    rule = request.path_params["rule"]

    settings_string = ""
    if config.mercure.rules[rule].processing_settings:
        settings_string = json.dumps(config.mercure.rules[rule].processing_settings, indent=4, sort_keys=False)

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
        "processing_settings": settings_string,
        "process_runner": config.mercure.process_runner
    }
    context.update(get_user_information(request))

    template = "rules_edit.html"
    return templates.TemplateResponse(template, context)


@router.post("/edit/{rule}")
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

    old_rule = config.mercure.rules[editrule]
    # Ensure that the processing settings are valid. Should happen on the client side too, but can't hurt
    # to check again
    try:
        new_processing_settings: Dict = json.loads(form.get("processing_settings", "{}"))
    except:
        new_processing_settings = {}

    # new_rule = Rule(
    #     disabled=form["status_disabled"],
    #     fallback=form["status_fallback"],
    #     processing_settings=new_processing_settings,
    #     **{
    #         k: form[k]
    #         for k in (
    #             "rule",
    #             "target",
    #             "contact",
    #             "comment",
    #             "tags",
    #             "action",
    #             "action_trigger",
    #             "study_trigger_condition",
    #             "study_trigger_series",
    #             "priority",
    #             "processing_module",
    #             "processing_retain_images",
    #             "notification_webhook",
    #             "notification_payload",
    #             "notification_trigger_reception",
    #             "notification_trigger_completion",
    #             "notification_trigger_error",
    #         )
    #     },
    # )
    if "processing_module_list" in form:
        processing_module = form.get("processing_module_list","").split(",")
        if processing_module == [""]:
            processing_module = ""
    else:
        processing_module = form.get("processing_module", "")
        
    notification_payload = form.get("notification_payload", "")
    notification_payload = notification_payload.strip().lstrip("{").rstrip("}")
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
        processing_module=processing_module,
        processing_settings=new_processing_settings,
        processing_retain_images=form.get("processing_retain_images", "False"),
        notification_webhook=form.get("notification_webhook", ""),
        notification_email=form.get("notification_email", ""),
        notification_payload=notification_payload,
        notification_payload_body=form.get("notification_payload_body", ""),
        notification_email_body=form.get("notification_email_body", ""),
        notification_email_type="html" if form.get("notification_email_html",False) else "plain",
        notification_trigger_reception=form.get("notification_trigger_reception", "False"),
        notification_trigger_completion=form.get("notification_trigger_completion", "False"),
        notification_trigger_completion_on_request=form.get("notification_trigger_completion_on_request", "False"),
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


@router.post("/delete/{rule}")
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


@router.post("/test")
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
    try:
        result = rule_evaluation.eval_rule(testrule, testvalues)
        if result:
            return PlainTextResponse(
                f'<span class="tag is-success is-medium ruleresult"><i class="fas fa-thumbs-up"></i>&nbsp;Trigger</span>' + (f'<pre style="display:inline; margin-left: 1em">{result}</pre>' if result is not True else '')
            )
        else:
            return PlainTextResponse(
                f'<span class="tag is-info is-medium ruleresult"><i class="fas fa-thumbs-down"></i>&nbsp;Reject</span>' + (f'<pre style="display:inline; margin-left: 1em">{result}</pre>' if result is not False else '')
            )
    except TagNotFoundException as e:
        return PlainTextResponse(
                f'<span class="tag is-info is-medium ruleresult"><i class="fas fa-thumbs-down"></i>&nbsp;Reject</span><span>{e}</span>'
            )
    except Exception as e:
        return PlainTextResponse(
            f'<span class="tag is-danger is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid rule: <pre style="display:inline; margin-left: 1em">{e}</pre>'
        )


@router.post("/test_completionseries")
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

rules_app = Starlette(routes=router)
