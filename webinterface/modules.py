from starlette.applications import Starlette
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

import common.helper as helper
import common.config as config
import common.monitor as monitor
from common.constants import mercure_defs
from webinterface.common import get_user_information
from webinterface.common import templates

modules_app = Starlette()

###################################################################################
## Modules endpoints
###################################################################################

@modules_app.route('/', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_modules(request):
    """Shows all installed modules"""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    used_modules = {}
    for rule in config.mercure["rules"]:
        used_module=config.mercure["rules"][rule].get("processing_module","NONE")
        used_modules[used_module]=rule

    template = "modules.html"
    context = {"request": request, "mercure_version": mercure_defs.VERSION, "page": "modules", 
               "modules": config.mercure["modules"], "used_modules": used_modules}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)

@modules_app.route('/', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def add_module(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    name=form.get("name","")
    if name in config.mercure["modules"]:
        return PlainTextResponse('Name already exists.')    

    config.mercure["modules"][name] = { 
        "url": form.get("url",""),
        "docker_tag": form.get("docker_tag",None)
    }
    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')
    # logger.info(f'Created rule {newrule}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)    
    return RedirectResponse(url='/modules/', status_code=303)  
    


@modules_app.route('/edit/{module}', methods=["GET"])
@requires('authenticated', redirect='login')
async def edit_module(request):
    """Shows all installed modules"""
    module = request.path_params["module"]
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "modules_edit.html"
    context = {"request": request, "mercure_version": mercure_defs.VERSION, "page": "modules", 
               "module": config.mercure["modules"][module], "module_name":module}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@modules_app.route('/edit/{module}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def edit_module(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    form = dict(await request.form())
    
    name= request.path_params["module"]
    if name in config.mercure["modules"]:        
        config.mercure["modules"][name] = { 
            "url": form.get("url",""),
            "docker_tag": form.get("docker_tag",None)
        }
    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')
    # logger.info(f'Created rule {newrule}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)    
    return RedirectResponse(url='/modules/', status_code=303)  

@modules_app.route('/delete/{module}', methods=["POST"])
@requires(['authenticated','admin'], redirect='login')
async def delete_module(request):
    """Creates a new routing rule and forwards the user to the rule edit page."""
    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    name= request.path_params["module"]
    if name in config.mercure["modules"]:        
        del config.mercure["modules"][name]

    try: 
        config.save_config()
    except:
        return PlainTextResponse('ERROR: Unable to write configuration. Try again.')
    # logger.info(f'Created rule {newrule}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)    
    return RedirectResponse(url='/modules/', status_code=303)  
