"""
webgui.py
=========
The web-based graphical user interface of mercure.
"""
import uvicorn
import base64
import binascii
import sys
import shutil
import json
import distro
import random
import os
import asyncio
import datetime
import logging
import daiquiri
import html
from pathlib import Path

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.responses import HTMLResponse
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from starlette.authentication import requires
from starlette.authentication import (
    AuthenticationBackend, AuthenticationError, SimpleUser, 
    UnauthenticatedUser, AuthCredentials
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
import common.version as version
import common.rule_evaluation as rule_evaluation
import webinterface.users as users
import webinterface.tagslist as tagslist
import webinterface.services as services
import webinterface.modules as modules
import webinterface.queue as queue
from webinterface.common import templates
from webinterface.common import get_user_information


###################################################################################
## Helper classes
###################################################################################

daiquiri.setup(
    level=logging.INFO,
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt="%(color)s%(levelname)-8.8s "
                "%(name)s: %(message)s%(color_stop)s"
            )
        ),
    ),
)
logger = daiquiri.getLogger("webgui")


class ExtendedUser(SimpleUser):
    def __init__(self, username: str, is_admin: False) -> None:
        self.username = username
        self.admin_status = is_admin

    @property
    def is_admin(self) -> bool:
        return self.admin_status


class SessionAuthBackend(AuthenticationBackend):
    async def authenticate(self, request):

        username=request.session.get("user")
        if username==None:
            return

        credentials=["authenticated"]
        is_admin=False

        if request.session.get("is_admin", "False")=="Jawohl":
            credentials.append("admin")
            is_admin=True

        return AuthCredentials(credentials), ExtendedUser(username,is_admin)


webgui_config = Config("configuration/webgui.env")
# Note: PutSomethingRandomHere is the default value in the shipped configuration file.
#       The app will not start with this value, forcing the users to set their onw secret 
#       key. Therefore, the value is used as default here as well.
SECRET_KEY  = webgui_config('SECRET_KEY', cast=Secret, default="PutSomethingRandomHere")
WEBGUI_PORT = webgui_config('PORT',  cast=int, default=8000)
WEBGUI_HOST = webgui_config('HOST',  default='0.0.0.0')
DEBUG_MODE  = webgui_config('DEBUG', cast=bool, default=True)

app = Starlette(debug=DEBUG_MODE)
# Don't check the existence of the static folder because the wrong parent folder is used if the 
# source code is parsed by sphinx. This would raise an exception and lead to failure of sphix.
app.mount('/static', StaticFiles(directory='webinterface/statics', check_dir=False), name='static')
app.add_middleware(AuthenticationMiddleware, backend=SessionAuthBackend())
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="mercure_session")
app.mount("/modules", modules.modules_app)
app.mount("/queue", queue.queue_app)

async def async_run(cmd):
    """Executes the given command in a way compatible with ayncio."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    return proc.returncode,stdout,stderr


###################################################################################
## Logs endpoints
###################################################################################

@app.route('/logs')
@requires(['authenticated','admin'], redirect='login')
async def show_first_log(request):
    """Get the first service entry and forward to corresponding log entry point."""
    if (services.services_list):
        first_service=next(iter(services.services_list))
        return RedirectResponse(url='/logs/'+first_service, status_code=303)  
    else:
        return PlainTextResponse('No services configured')


@app.route('/logs/{service}')
@requires(['authenticated','admin'], redirect='login')
async def show_log(request):
    """Render the log for the given service. The time range can be specified via URL parameters."""
    requested_service=request.path_params["service"]

    # Get optional start and end dates from the URL. Make sure 
    # that the date format is clean
    try:
        start_date=request.query_params.get("from","")
        start_time=request.query_params.get("from_time","")
        datetime.datetime.strptime(start_date, '%Y-%m-%d')
        start_date_cmd=' --since "'+start_date
        if start_date and start_time:
            datetime.datetime.strptime(start_time, '%H:%M')
            start_date_cmd = start_date_cmd + " " + start_time
        start_date_cmd=start_date_cmd+'"'
    except: 
        start_date=""
        start_time=""
        start_date_cmd=""

    try:
        end_date=request.query_params.get("to","")
        end_time=request.query_params.get("to_time","")        
        datetime.datetime.strptime(end_date, '%Y-%m-%d')
        end_date_cmd=' --until "'+end_date
        if end_date and end_time:
            datetime.datetime.strptime(end_time, '%H:%M')
            end_date_cmd = end_date_cmd + " " + end_time
        end_date_cmd=end_date_cmd+'"'
    except: 
        end_date=""
        end_time=""
        end_date_cmd=""

    service_logs = {}
    for service in services.services_list:
        service_logs[service]={ "id": service, "name": services.services_list[service]["name"], "systemd": services.services_list[service]["systemd_service"] }

    if (not requested_service in service_logs) or (not services.services_list[requested_service]["systemd_service"]):
        return PlainTextResponse('Service does not exist or is incorrectly configured.')

    run_result=await async_run('journalctl -n 1000 -u ' + services.services_list[requested_service]["systemd_service"]
                               + start_date_cmd + end_date_cmd)

    log_content=""

    if run_result[0]==0:
        log_content=html.escape(str(run_result[1].decode()))
        line_list=log_content.split('\n')
        if len(line_list) and (not line_list[-1]):
            del line_list[-1]

        log_content='<br />'.join(line_list)
    else:
        log_content="Error reading log information."
        if start_date or end_date:
            log_content=log_content+"<br /><br />Are the From/To settings valid?"

    template = "logs.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "logs", 
               "service_logs": service_logs, "log_id": requested_service, "log_content": log_content,
               "start_date": start_date, "start_time": start_time, "end_date": end_date, "end_time": end_time }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


###################################################################################
## Rules endpoints
###################################################################################

@app.route('/rules', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_rules(request):
    """Show all defined routing rules. Can be executed by all logged-in users."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "rules.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "rules", "rules": config.mercure["rules"]}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/rules', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def add_rule(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newrule=form.get("name","")
    if newrule in config.mercure["rules"]:
        return PlainTextResponse('Rule already exists.')
    
    config.mercure["rules"][newrule]={ "rule": "False" }

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    logger.info(f'Created rule {newrule}')
    monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)    
    return RedirectResponse(url='/rules/edit/'+newrule, status_code=303)  


@app.route('/rules/edit/{rule}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit(request):
    """Shows the edit page for the given routing rule."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    rule=request.path_params["rule"]
    template = "rules_edit.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "rules", "rules": config.mercure["rules"], 
               "targets": config.mercure["targets"], "modules": config.mercure["modules"], "rule": rule, 
               "alltags": tagslist.alltags, "sortedtags": tagslist.sortedtags}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/rules/edit/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit_post(request):
    """Updates the settings for the given routing rule."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    editrule=request.path_params["rule"]
    form = dict(await request.form())

    if not editrule in config.mercure["rules"]:
        return PlainTextResponse('Rule does not exist anymore.')

    config.mercure["rules"][editrule]["rule"]=form.get("rule","False")
    config.mercure["rules"][editrule]["target"]=form.get("target","")
    config.mercure["rules"][editrule]["disabled"]=form.get("disabled","False")
    config.mercure["rules"][editrule]["contact"]=form.get("contact","")
    config.mercure["rules"][editrule]["comment"]=form.get("comment","")
    config.mercure["rules"][editrule]["action"]=form.get("action","route")
    config.mercure["rules"][editrule]["action_trigger"]=form.get("action_trigger","series")
    config.mercure["rules"][editrule]["priority"]=form.get("priority","normal")
    config.mercure["rules"][editrule]["processing_module"]=form.get("processing_module","")
    config.mercure["rules"][editrule]["processing_settings"]=form.get("processing_settings","")
    config.mercure["rules"][editrule]["notification_webhook"]=form.get("notification_webhook","")
    config.mercure["rules"][editrule]["notification_payload"]=form.get("notification_payload","")
    config.mercure["rules"][editrule]["notification_trigger_reception"]=form.get("notification_trigger_reception","False")
    config.mercure["rules"][editrule]["notification_trigger_completion"]=form.get("notification_trigger_completion","False")
    config.mercure["rules"][editrule]["notification_trigger_error"]=form.get("notification_trigger_error","False")

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    logger.info(f'Edited rule {editrule}')
    monitor.send_webgui_event(monitor.w_events.RULE_EDIT, request.user.display_name, editrule)    
    return RedirectResponse(url='/rules', status_code=303)   


@app.route('/rules/delete/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_delete_post(request):
    """Deletes the given routing rule"""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    deleterule=request.path_params["rule"]    
   
    if deleterule in config.mercure["rules"]:
        del config.mercure["rules"][deleterule]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')
    
    logger.info(f'Deleted rule {deleterule}')    
    monitor.send_webgui_event(monitor.w_events.RULE_DELETE, request.user.display_name, deleterule)    
    return RedirectResponse(url='/rules', status_code=303)   


@app.route('/rules/test', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_test(request):
    """Evalutes if a given routing rule is valid. The rule and testing dictionary have to be passed as form parameters."""
    try:
        form = dict(await request.form())
        testrule=form["rule"]
        testvalues=json.loads(form["testvalues"])
    except: 
        return PlainTextResponse('<span class="tag is-warning is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid test values')
    
    result=rule_evaluation.test_rule(testrule,testvalues)

    if (result=="True"):
        return PlainTextResponse('<span class="tag is-success is-medium ruleresult"><i class="fas fa-thumbs-up"></i>&nbsp;Route</span>')
    else:
        if (result=="False"):
            return PlainTextResponse('<span class="tag is-info is-medium ruleresult"><i class="fas fa-thumbs-down"></i>&nbsp;Discard</span>')
        else:
            return PlainTextResponse('<span class="tag is-danger is-medium ruleresult"><i class="fas fa-bug"></i>&nbsp;Error</span>&nbsp;&nbsp;Invalid rule: '+result)


###################################################################################
## Targets endpoints
###################################################################################

@app.route('/targets', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_targets(request):
    """Shows all configured targets."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    used_targets = {}
    for rule in config.mercure["rules"]:
        used_target=config.mercure["rules"][rule].get("target","NONE")
        used_targets[used_target]=rule

    template = "targets.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "targets", "targets": config.mercure["targets"], "used_targets": used_targets}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/targets', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def add_target(request):
    """Creates a new target."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newtarget=form.get("name","")
    if newtarget in config.mercure["targets"]:
        return PlainTextResponse('Target already exists.')
    
    config.mercure["targets"][newtarget]={ "ip": "", "port": "" }

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    logger.info(f'Created target {newtarget}')
    monitor.send_webgui_event(monitor.w_events.TARGET_CREATE, request.user.display_name, newtarget)    
    return RedirectResponse(url='/targets/edit/'+newtarget, status_code=303)  


@app.route('/targets/edit/{target}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def targets_edit(request):
    """Shows the edit page for the given target."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edittarget=request.path_params["target"]

    if not edittarget in config.mercure["targets"]:
        return RedirectResponse(url='/targets', status_code=303) 

    template = "targets_edit.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "targets", "targets": config.mercure["targets"], "edittarget": edittarget}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/targets/edit/{target}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def targes_edit_post(request):
    """Updates the given target using the form values posted with the request."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edittarget=request.path_params["target"]
    form = dict(await request.form())

    if not edittarget in config.mercure["targets"]:
        return PlainTextResponse('Target does not exist anymore.')

    config.mercure["targets"][edittarget]["ip"]=form["ip"]
    config.mercure["targets"][edittarget]["port"]=form["port"]
    config.mercure["targets"][edittarget]["aet_target"]=form["aet_target"]
    config.mercure["targets"][edittarget]["aet_source"]=form["aet_source"]
    config.mercure["targets"][edittarget]["contact"]=form["contact"]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    logger.info(f'Edited target {edittarget}')
    monitor.send_webgui_event(monitor.w_events.TARGET_EDIT, request.user.display_name, edittarget)    
    return RedirectResponse(url='/targets', status_code=303)   


@app.route('/targets/delete/{target}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def targets_delete_post(request):
    """Deletes the given target."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    deletetarget=request.path_params["target"]

    if deletetarget in config.mercure["targets"]:
        del config.mercure["targets"][deletetarget]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')    

    logger.info(f'Deleted target {deletetarget}')
    monitor.send_webgui_event(monitor.w_events.TARGET_DELETE, request.user.display_name, deletetarget)    
    return RedirectResponse(url='/targets', status_code=303)   


@app.route('/targets/test/{target}', methods=["POST"])
@requires(['authenticated'], redirect='login')
async def targets_test_post(request):
    """Tests the connectivity of the given target by executing ping and c-echo requests."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    testtarget=request.path_params["target"]
    
    ping_response="False"
    cecho_response="False"
    target_ip=""
    target_port=""
    target_aec="ANY-SCP"
    target_aet="ECHOSCU"

    try:
        target_ip=config.mercure["targets"][testtarget]["ip"]
        target_port=config.mercure["targets"][testtarget]["port"]
        target_aec=config.mercure["targets"][testtarget]["aet_target"]
        target_aet=config.mercure["targets"][testtarget]["aet_source"]
    except:
        pass

    logger.info(f'Testing target {testtarget}')

    if (target_ip) and (target_port):
        if (await async_run("ping -w 1 -c 1 " + target_ip))[0]==0:
            ping_response="True"
            # Only test for c-echo if the ping was successful
            if (await async_run("echoscu -to 10 -aec " + target_aec + " -aet " + target_aet + " " + target_ip + " " + target_port))[0]==0:
                cecho_response="True"
    
    return JSONResponse('{"ping": "'+ping_response+'", "c-echo": "'+cecho_response+'" }')


###################################################################################
## Users endpoints
###################################################################################

@app.route('/users', methods=["GET"])
@requires(['authenticated','admin'], redirect='homepage')
async def show_users(request):
    """Shows all available users."""
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "users.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "users", "users": users.users_list }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/users', methods=["POST"])
@requires(['authenticated','admin'], redirect='homepage')
async def add_new_user(request):
    """Creates a new user and redirects to the user-edit page."""
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newuser=form.get("name","")
    if newuser in users.users_list:
        return PlainTextResponse('User already exists.')
    
    newpassword=users.hash_password(form.get("password","here_should_be_a_password"))
    users.users_list[newuser]={ "password": newpassword, "is_admin": "False", "change_password": "True" }

    try: 
        users.save_users()
    except:
        return PlainTextResponse('ERROR: Unable to write user list. Try again.')    

    logger.info(f'Created user {newuser}')
    monitor.send_webgui_event(monitor.w_events.USER_CREATE, request.user.display_name, newuser)    
    return RedirectResponse(url='/users/edit/'+newuser, status_code=303)  


@app.route('/users/edit/{user}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def users_edit(request):
    """Shows the settings for a given user."""
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edituser=request.path_params["user"]

    if not edituser in users.users_list:
        return RedirectResponse(url='/users', status_code=303) 

    template = "users_edit.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "users", 
               "edituser": edituser, "edituser_info": users.users_list[edituser]}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/settings', methods=["GET"])
@requires(['authenticated'], redirect='login')
async def settings_edit(request):
    """Shows the settings for the current user. Renders the same template as the normal user edit, but with parameter own_settings=True."""
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    own_name=request.user.display_name

    template = "users_edit.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "settings", 
               "edituser": own_name, "edituser_info": users.users_list[own_name], "own_settings": "True", 
               "change_password": users.users_list[own_name].get("change_password","False") }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/users/edit/{user}', methods=["POST"])
@requires(['authenticated'], redirect='login')
async def users_edit_post(request):
    """Updates the given user with settings passed as form parameters."""
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edituser=request.path_params["user"]
    form = dict(await request.form())

    if not edituser in users.users_list:
        return PlainTextResponse('User does not exist anymore.')

    users.users_list[edituser]["email"]=form["email"]
    if form["password"]:
        users.users_list[edituser]["password"]=users.hash_password(form["password"])
        users.users_list[edituser]["change_password"]="False"
 
    # Only admins are allowed to change the admin status, and the current user
    # cannot change the status for himself (which includes the settings page)
    if (request.user.is_admin) and (request.user.display_name != edituser):
        users.users_list[edituser]["is_admin"]=form["is_admin"]

    if (request.user.is_admin):
        users.users_list[edituser]["permissions"]=form["permissions"]

    try: 
        users.save_users()
    except:
        return PlainTextResponse('ERROR: Unable to write user list. Try again.')    

    logger.info(f'Edited user {edituser}')
    monitor.send_webgui_event(monitor.w_events.USER_EDIT, request.user.display_name, edituser)
    if "own_settings" in form:
        return RedirectResponse(url='/', status_code=303)   
    else:
        return RedirectResponse(url='/users', status_code=303)   


@app.route('/users/delete/{user}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def users_delete_post(request):
    """Deletes the given users."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    deleteuser=request.path_params["user"]

    if deleteuser in users.users_list:
        del users.users_list[deleteuser]

    try: 
        users.save_users()
    except:
        return PlainTextResponse('ERROR: Unable to write user list. Try again.')

    logger.info(f'Deleted user {deleteuser}')        
    monitor.send_webgui_event(monitor.w_events.USER_DELETE, request.user.display_name, deleteuser)
    return RedirectResponse(url='/users', status_code=303)   


###################################################################################
## Configuration endpoints
###################################################################################

@app.route('/configuration')
@requires(['authenticated','admin'], redirect='homepage')
async def configuration(request):
    """Shows the current configuration of the mercure appliance."""
    try: 
        config.read_config()
    except:
        pass
    template = "configuration.html"
    config_edited=int(request.query_params.get("edited",0))
    os_info=distro.linux_distribution()
    os_string=f"{os_info[0]} Version {os_info[1]} ({os_info[2]})"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "configuration", "config": config.mercure, "os_string": os_string, "config_edited": config_edited}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/configuration/edit')
@requires(['authenticated','admin'], redirect='homepage')
async def configuration_edit(request):
    """Shows a configuration editor"""

    # Check for existence of lock file
    cfg_file = Path(config.configuration_filename)
    cfg_lock=Path(cfg_file.parent/cfg_file.stem).with_suffix(".lock")
    if cfg_lock.exists():
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    try:
        with open(cfg_file, "r") as json_file:
            config_content=json.load(json_file)    
    except:
        return PlainTextResponse('Error reading configuration file.')

    config_content=json.dumps(config_content, indent=4, sort_keys=False)

    template = "configuration_edit.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "configuration", "config_content": config_content}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/configuration/edit', methods=["POST"])
@requires(['authenticated','admin'], redirect='homepage')
async def configuration_edit_post(request):
    """Updates the configuration after post from editor"""

    form = dict(await request.form())
    editor_json=form.get("editor","{}")
    try:
        validated_json=json.loads(editor_json)
    except ValueError:
        return PlainTextResponse('Invalid JSON data transferred.')

    try:
        config.write_configfile(validated_json)
        config.read_config()
    except ValueError:
        return PlainTextResponse('Unable to write config file. Might be locked.')

    logger.info(f'Updates mercure configuration file.')     
    monitor.send_webgui_event(monitor.w_events.CONFIG_EDIT, request.user.display_name, "")

    return RedirectResponse(url='/configuration?edited=1', status_code=303)


###################################################################################
## Login/logout endpoints
###################################################################################

@app.route('/login', methods=["GET"])
async def login(request):
    """Shows the login page."""
    request.session.clear()
    template = "login.html"
    context = {"request": request, "mercure_version": version.mercure_version, "appliance_name": config.mercure.get('appliance_name','mercure Router') }
    return templates.TemplateResponse(template, context)


@app.route("/login", methods=["POST"])
async def login_post(request):
    """Evaluate the submitted login information. Redirects to index page if login information valid, otherwise back to login. 
       On the first login, the user will be directed to the settings page and asked to change the password."""    
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())

    if users.evaluate_password(form.get("username",""),form.get("password","")):        
        request.session.update({"user": form["username"]})

        if users.is_admin(form["username"])==True:
            request.session.update({"is_admin": "Jawohl"})

        monitor.send_webgui_event(monitor.w_events.LOGIN, form["username"], "{admin}".format(admin="ADMIN" if users.is_admin(form["username"]) else ""))

        if users.needs_change_password(form["username"]):
            return RedirectResponse(url='/settings', status_code=303)
        else:
            return RedirectResponse(url='/', status_code=303)
    else:        
        if request.client.host is None:
            source_ip="UNKOWN IP"
        else:
            source_ip=request.client.host
        monitor.send_webgui_event(monitor.w_events.LOGIN_FAIL, form["username"], source_ip)

        template = "login.html"
        context = {"request": request, "invalid_password": 1, "mercure_version": version.mercure_version, "appliance_name": config.mercure.get('appliance_name','mercure Router') }
        return templates.TemplateResponse(template, context)


@app.route('/logout')
async def logout(request):
    """Logouts the users by clearing the session cookie."""    
    monitor.send_webgui_event(monitor.w_events.LOGOUT, request.user.display_name, "")
    request.session.clear()
    return RedirectResponse(url='/login')


###################################################################################
## Homepage endpoints
###################################################################################

@app.route('/')
@requires('authenticated', redirect='login')
async def homepage(request):
    """Renders the index page that shows information about the system status."""
    used_space=0
    free_space=0
    total_space=0

    try:
        disk_total, disk_used, disk_free = shutil.disk_usage(config.mercure["incoming_folder"])

        if (disk_total==0):
            disk_total=1

        used_space=100*disk_used/disk_total
        free_space=(disk_free // (2**30))
        total_space=(disk_total // (2**30))
    except:
        used_space=-1
        free_space="N/A"
        disk_total="N/A"

    service_status = {}
    for service in services.services_list:
        running_status="False"

        if (services.services_list[service].get("systemd_service","")):
            if (await async_run("systemctl is-active " + services.services_list[service]["systemd_service"]))[0]==0:
                running_status="True"
        
        service_status[service]={ "id": service, "name": services.services_list[service]["name"], "running": running_status }
        
    template = "index.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "homepage", 
               "used_space": used_space, "free_space": free_space, "total_space": total_space,
               "service_status": service_status }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/services/control', methods=["POST"])
@requires(['authenticated','admin'], redirect='homepage')
async def control_services(request):
    form = dict(await request.form())
    action=''

    if form.get('action','')=='start':
        action='start'
    if form.get('action','')=='stop':
        action='stop'
    if form.get('action','')=='restart':
        action='restart'
    if form.get('action','')=='kill':
        action='kill'

    controlservices=form.get('services','').split(",")

    if action and len(controlservices)>0:
        for service in controlservices:
            if not str(service) in services.services_list:
                continue                            
            command="systemctl "+action+" "+services.services_list[service]["systemd_service"]
            logger.info(f'Executing: {command}')
            await async_run(command)

    monitor_string="action: "+action+"; services: "+form.get('services','')
    monitor.send_webgui_event(monitor.w_events.SERVICE_CONTROL, request.user.display_name, monitor_string)
    return JSONResponse("{ }")


###################################################################################
## Error handlers
###################################################################################

@app.route('/error')
async def error(request):
    """
    An example error. Switch the `debug` setting to see either tracebacks or 500 pages.
    """
    raise RuntimeError("Oh no")


@app.exception_handler(404)
async def not_found(request, exc):
    """
    Return an HTTP 404 page.
    """
    template = "404.html"
    context = {"request": request, "mercure_version": version.mercure_version }
    return templates.TemplateResponse(template, context, status_code=404)


@app.exception_handler(500)
async def server_error(request, exc):
    """
    Return an HTTP 500 page.
    """
    template = "500.html"
    context = {"request": request, "mercure_version": version.mercure_version }
    return templates.TemplateResponse(template, context, status_code=500)


###################################################################################
## Emergency error handler
###################################################################################

async def emergency_response(request):
    """Shows emergency message about invalid configuration."""
    return PlainTextResponse('ERROR: mercure configuration is invalid. Check configuration and restart webgui service.')

def launch_emergency_app():
    """Launches a minimal application to inform the user about the incorrect configuration"""
    emergency_app = Starlette(debug=True)
    emergency_app = Router([
        Route('/{whatever:path}', endpoint=emergency_response, methods=['GET','POST']),
    ])
    uvicorn.run(emergency_app, host=WEBGUI_HOST, port=WEBGUI_PORT)


###################################################################################
## Entry function
###################################################################################

if __name__ == "__main__":
    try:
        services.read_services()
        config.read_config()
        users.read_users()        
        if (str(SECRET_KEY)=='PutSomethingRandomHere'):
            logger.error("You need to change the SECRET_KEY in configuration/webgui.env")
            raise Exception("Invalid or missing SECRET_KEY in webgui.env")
    except Exception as e: 
        logger.error(e)
        logger.error("Cannot start service. Showing emergency message.")
        launch_emergency_app()
        logger.info("Going down.")
        sys.exit(1)

    monitor.configure('webgui','main',config.mercure['bookkeeper'])
    monitor.send_event(monitor.h_events.BOOT,monitor.severity.INFO,f'PID = {os.getpid()}')    

    try:
        tagslist.read_tagslist()
    except Exception as e: 
        logger.info(e)
        logger.info("Unable to parse tag list. Rule evaluation will not be available.")

    uvicorn.run(app, host=WEBGUI_HOST, port=WEBGUI_PORT)

    # Process will exit here
    monitor.send_event(monitor.h_events.SHUTDOWN,monitor.severity.INFO,'')    
