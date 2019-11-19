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

queue_app = Starlette()

###################################################################################
## Queue endpoints
###################################################################################

@queue_app.route('/', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_queues(request):
    """Shows all installed modules"""

    try: 
        config.read_config()
    except:
        return PlainTextResponse('Configuration is being updated. Try again in a minute.')

    template = "queue.html"
    context = {"request": request, "hermes_version": version.hermes_version, "page": "queue"}
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)

@queue_app.route('/jobs/processing', methods=["GET"])
@requires('authenticated', redirect='login')
async def show_jobs_processing(request):

    job_list={}
    job_list["1234-1234-1234-1234"]={"Module": "Test", "ACC": "ACC1234", "MRN": "MRN1234", "Status": "Processing"}
    job_list["1334-1244-2234-1233"]={"Module": "Anonymizer", "ACC": "ACC1234", "MRN": "MRN1234", "Status": "Scheduled"}
    job_list["4234-1234-1434-1234"]={"Module": "Anonymizer", "ACC": "ACC1234", "MRN": "MRN1234", "Status": "Scheduled"}

    return JSONResponse(job_list)

