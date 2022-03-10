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


logger = daiquiri.getLogger("test")


###################################################################################
## Test endpoints
###################################################################################


test_app = Starlette()


@test_app.route("/", methods=["GET"])
@requires("authenticated", redirect="login")
async def index(request):
    template = "test.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "test",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)
