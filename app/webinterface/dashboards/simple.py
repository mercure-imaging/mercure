import common.config as config
from starlette.authentication import requires
# App-specific includes
from webinterface.common import templates

from .common import router

logger = config.get_logger()


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
