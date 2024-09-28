"""
test.py
========
Test page for querying the bookkeeper database from the webgui.
"""

# Standard python includes
import daiquiri

# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires

# App-specific includes
from common.constants import mercure_defs
from webinterface.common import get_user_information
from webinterface.common import templates
import common.config as config
from starlette.responses import RedirectResponse
from decoRouter import Router as decoRouter
router = decoRouter()

logger = config.get_logger()

###################################################################################
## Test endpoints
###################################################################################

@router.get("/")
async def index(request):
    return RedirectResponse(url="tests")


@router.get("/tasks")
@requires("authenticated", redirect="login")
async def tasks(request):
    template = "dashboards/tasks.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "tools",
        "tab": "tasks",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.get("/tests")
@requires(["authenticated", "admin"], redirect="login")
async def tests(request):
    template = "dashboards/tests.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "tools",
        "tab": "tests",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)

dashboards_app = Starlette(routes=router)