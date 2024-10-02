from .common import router
from starlette.authentication import requires

# App-specific includes
from common.constants import mercure_defs
from webinterface.common import get_user_information, templates
import common.config as config
logger = config.get_logger()
from .common import router

@router.get("/tasks")
@requires("authenticated", redirect="login")
async def tasks(request):
    template = "dashboards/tasks.html"
    context = {
        "request": request,
        "page": "tools",
        "tab": "tasks",
    }
    return templates.TemplateResponse(template, context)


@router.get("/tests")
@requires(["authenticated", "admin"], redirect="login")
async def tests(request):
    template = "dashboards/tests.html"
    context = {
        "request": request,
        "page": "tools",
        "tab": "tests",
    }
    return templates.TemplateResponse(template, context)