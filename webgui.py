import uvicorn
import base64
import binascii
import sys
import shutil
import json
import distro
import random
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

# App-specific includes
import common.helper as helper
import common.config as config
import common.rule_evaluation as rule_evaluation
import webgui.users as users
import webgui.tagslist as tagslist
import webgui.services as services


hermes_version = "0.1a"


###################################################################################
## Helper classes
###################################################################################

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
SECRET_KEY = webgui_config('SECRET_KEY', cast=Secret, default="NONE")
WEBGUI_PORT = webgui_config('PORT', cast=int, default=8000)
WEBGUI_HOST = webgui_config('HOST', default='0.0.0.0')
templates = Jinja2Templates(directory='webgui/templates')

app = Starlette(debug=True)
app.mount('/static', StaticFiles(directory='webgui/statics'), name='static')
app.add_middleware(AuthenticationMiddleware, backend=SessionAuthBackend())
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


def get_user_information(request):
    return { "logged_in": request.user.is_authenticated, "user": request.user.display_name, "is_admin": request.user.is_admin }


###################################################################################
## Logs endpoints
###################################################################################

@app.route('/logs')
@requires('authenticated', redirect='login')
async def show_first_log(request):
    # Get first service entry and forward to corresponding entry point
    if (services.services_list):
        first_service=next(iter(services.services_list))
        return RedirectResponse(url='/logs/'+first_service, status_code=303)  
    else:
        return PlainTextResponse('No services configured')


@app.route('/logs/{service}')
@requires('authenticated', redirect='login')
async def show_log(request):
    requested_service=request.path_params["service"]

    service_logs = {}
    for service in services.services_list:
        service_logs[service]={ "id": service, "name": services.services_list[service]["name"] }

    if not requested_service in service_logs:
        return PlainTextResponse('Service does not exist.')

    template = "logs.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "logs", 
               "service_logs": service_logs, "log_id": requested_service }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


###################################################################################
## Rules endpoints
###################################################################################

@app.route('/rules', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_rules(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "rules.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "rules", "rules": config.hermes["rules"]}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/rules', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def add_rule(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newrule=form.get("name","")
    if newrule in config.hermes["rules"]:
        return PlainTextResponse('Rule already exists.')
    
    config.hermes["rules"][newrule]={ "rule": "False" }

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    print("Created rule ", newrule)
    return RedirectResponse(url='/rules/edit/'+newrule, status_code=303)  


@app.route('/rules/edit/{rule}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    rule=request.path_params["rule"]
    template = "rules_edit.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "rules", "rules": config.hermes["rules"], 
               "targets": config.hermes["targets"], "rule": rule, 
               "alltags": tagslist.alltags, "sortedtags": tagslist.sortedtags}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/rules/edit/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_edit_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    editrule=request.path_params["rule"]
    form = dict(await request.form())

    if not editrule in config.hermes["rules"]:
        return PlainTextResponse('Rule does not exist anymore.')

    config.hermes["rules"][editrule]["rule"]=form["rule"]
    config.hermes["rules"][editrule]["target"]=form["target"]
    config.hermes["rules"][editrule]["disabled"]=form["disabled"]
    config.hermes["rules"][editrule]["contact"]=form["contact"]
    config.hermes["rules"][editrule]["comment"]=form["comment"]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    print("Edited rule ", editrule)
    return RedirectResponse(url='/rules', status_code=303)   


@app.route('/rules/delete/{rule}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_delete_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    deleterule=request.path_params["rule"]    
   
    if deleterule in config.hermes["rules"]:
        del config.hermes["rules"][deleterule]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')
    
    print("Deleted rule ", deleterule)
    return RedirectResponse(url='/rules', status_code=303)   


@app.route('/rules/test', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def rules_test(request):
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
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    used_targets = {}
    for rule in config.hermes["rules"]:
        used_target=config.hermes["rules"][rule].get("target","NONE")
        used_targets[used_target]=rule

    template = "targets.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "targets", "targets": config.hermes["targets"], "used_targets": used_targets}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@app.route('/targets', methods=["POST"])
@requires('authenticated', redirect='login')
async def add_target(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newtarget=form.get("name","")
    if newtarget in config.hermes["targets"]:
        return PlainTextResponse('Target already exists.')
    
    config.hermes["targets"][newtarget]={ "ip": "", "port": "" }

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    print("Created target ", newtarget)
    return RedirectResponse(url='/targets/edit/'+newtarget, status_code=303)  


@app.route('/targets/edit/{target}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def targets_edit(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edittarget=request.path_params["target"]

    if not edittarget in config.hermes["targets"]:
        return RedirectResponse(url='/targets', status_code=303) 

    template = "targets_edit.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "targets", "targets": config.hermes["targets"], "edittarget": edittarget}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/targets/edit/{target}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def targes_edit_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edittarget=request.path_params["target"]
    form = dict(await request.form())

    if not edittarget in config.hermes["targets"]:
        return PlainTextResponse('Target does not exist anymore.')

    config.hermes["targets"][edittarget]["ip"]=form["ip"]
    config.hermes["targets"][edittarget]["port"]=form["port"]
    config.hermes["targets"][edittarget]["aet_target"]=form["aet_target"]
    config.hermes["targets"][edittarget]["aet_source"]=form["aet_source"]
    config.hermes["targets"][edittarget]["contact"]=form["contact"]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')

    print("Edited target ", edittarget)
    return RedirectResponse(url='/targets', status_code=303)   


@app.route('/targets/delete/{target}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def targets_delete_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')
    
    deletetarget=request.path_params["target"]

    if deletetarget in config.hermes["targets"]:
        del config.hermes["targets"][deletetarget]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')    

    print("Deleted target ", deletetarget)
    return RedirectResponse(url='/targets', status_code=303)   


@app.route('/targets/test/{target}', methods=["POST"])
@requires(['authenticated'], redirect='login')
async def targets_test_post(request):
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    testtarget=request.path_params["target"]
   
    # TODO: Ping and c-echo target

    print("Testing target ", testtarget)
    return JSONResponse('{"ping": "True", "c-echo": "False" }')


###################################################################################
## Users endpoints
###################################################################################

@app.route('/users', methods=["GET"])
@requires(['authenticated','admin'], redirect='homepage')
async def show_users(request):
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "users.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "users", "users": users.users_list }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/users', methods=["POST"])
@requires(['authenticated','admin'], redirect='homepage')
async def add_new_user(request):
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    newuser=form.get("name","")
    if newuser in users.users_list:
        return PlainTextResponse('User already exists.')
    
    newpassword=form.get("password","here_should_be_a_password")
    users.users_list[newuser]={ "password": newpassword, "is_admin": "False" }

    try: 
        users.save_users()
    except:
        return PlainTextResponse('ERROR: Unable to write user list. Try again.')    

    print("Created user ", newuser)
    return RedirectResponse(url='/users/edit/'+newuser, status_code=303)  


@app.route('/users/edit/{user}', methods=["GET"])
@requires(['authenticated','admin'], redirect='login')
async def users_edit(request):
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    edituser=request.path_params["user"]

    if not edituser in users.users_list:
        return RedirectResponse(url='/users', status_code=303) 

    template = "users_edit.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "users", "users": users.users_list, "edituser": edituser}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


@app.route('/users/edit/{user}', methods=["POST"])
@requires(['authenticated'], redirect='login')
async def users_edit_post(request):
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
        users.users_list[edituser]["password"]=form["password"]

    # Only admins are allowed to change the admin status, and the current user
    # cannot change the status for himself (which includes the settings page)
    if (request.user.is_admin) and (request.user.display_name != edituser):
        users.users_list[edituser]["is_admin"]=form["is_admin"]

    try: 
        users.save_users()
    except:
        return PlainTextResponse('ERROR: Unable to write user list. Try again.')    

    print("Edited user ", edituser)
    if "own_settings" in form:
        return RedirectResponse(url='/', status_code=303)   
    else:
        return RedirectResponse(url='/users', status_code=303)   


@app.route('/users/delete/{user}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def users_delete_post(request):
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

    print("Deleted user ", deleteuser)
    return RedirectResponse(url='/users', status_code=303)   


@app.route('/settings', methods=["GET"])
@requires(['authenticated'], redirect='login')
async def settings_edit(request):
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "users_edit.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "settings", "users": users.users_list, "edituser": request.user.display_name, "own_settings": "True"}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)    


###################################################################################
## Configuration endpoints
###################################################################################

@app.route('/configuration')
@requires(['authenticated','admin'], redirect='homepage')
async def configuration(request):
    template = "configuration.html"
    os_info=distro.linux_distribution()
    os_string=f"{os_info[0]} Version {os_info[1]} ({os_info[2]})"
    context = {"request": request, "hermes_version": hermes_version, "page": "configuration", "config": config.hermes, "os_string": os_string}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


###################################################################################
## Login/logout endpoints
###################################################################################

@app.route('/login')
async def login(request):
    request.session.clear()
    template = "login.html"
    context = {"request": request, "hermes_version": hermes_version }
    return templates.TemplateResponse(template, context)


@app.route("/login", methods=["POST"])
async def login_post(request):
    try: 
        users.read_users()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())

    if users.evaluate_password(form.get("username",""),form.get("password","")):        
        request.session.update({"user": form["username"]})

        if users.is_admin(form["username"])==True:
            request.session.update({"is_admin": "Jawohl"})

        return RedirectResponse(url='/', status_code=303)
    else:
        template = "login.html"
        context = {"request": request, "invalid_password": 1 }
        return templates.TemplateResponse(template, context)


@app.route('/logout')
async def logout(request):
    request.session.clear()
    return RedirectResponse(url='/login')


###################################################################################
## Homepage endpoints
###################################################################################

@app.route('/')
@requires('authenticated', redirect='login')
async def homepage(request):

    used_space=0
    free_space=0
    total_space=0

    try:
        disk_total, disk_used, disk_free = shutil.disk_usage(config.hermes["incoming_folder"])

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
        if random.randint(0,1)==0:
            service_status[service]={ "id": service, "name": services.services_list[service]["name"], "running": "True" }
        else:
            service_status[service]={ "id": service, "name": services.services_list[service]["name"], "running": "False" }

    template = "index.html"
    context = {"request": request, "hermes_version": hermes_version, "page": "homepage", 
               "used_space": used_space, "free_space": free_space, "total_space": total_space,
               "service_status": service_status }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


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
    context = {"request": request, "hermes_version": hermes_version }
    return templates.TemplateResponse(template, context, status_code=404)


@app.exception_handler(500)
async def server_error(request, exc):
    """
    Return an HTTP 500 page.
    """
    template = "500.html"
    context = {"request": request, "hermes_version": hermes_version }
    return templates.TemplateResponse(template, context, status_code=500)


###################################################################################
## Entry function
###################################################################################

if __name__ == "__main__":
    try:
        services.read_services()
        config.read_config()
        users.read_users()
    except Exception as e: 
        print(e)
        print("Cannot start service. Going down.")
        print("")
        sys.exit(1)

    try:
        tagslist.read_tagslist()
    except Exception as e: 
        print(e)
        print("Unable to parse tag list. Rule evaluation will not be available.")

    if (SECRET_KEY=='NONE'):
        print("ERROR: No secret key defined! Not starting service.")
        sys.exit(1)

    uvicorn.run(app, host=WEBGUI_HOST, port=WEBGUI_PORT)
