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

config = config.get_logger()


###################################################################################
## Test endpoints
###################################################################################


test_app = Starlette()


@test_app.route("/tasks", methods=["GET"])
@requires("authenticated", redirect="login")
async def tasks(request):
    template = "dashboards/tasks.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "test",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@test_app.route("/tests", methods=["GET"])
@requires(["authenticated", "admin"], redirect="login")
async def tests(request):
    template = "dashboards/tests.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "test",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)
