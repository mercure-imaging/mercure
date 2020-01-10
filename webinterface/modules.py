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
import common.version as version
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
    for rule in config.hermes["rules"]:
        used_module=config.hermes["rules"][rule].get("processing_module","NONE")
        used_modules[used_module]=rule

    template = "modules.html"
    context = {"request": request, "mercure_version": version.mercure_version, "page": "modules", 
               "modules": config.hermes["modules"], "used_modules": used_modules}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)
