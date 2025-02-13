from starlette.applications import Starlette

from . import dicomweb, query_routes, simple  # noqa: F401
from .common import router

dashboards_app = Starlette(routes=router)
dashboards_app.mount("/dicomweb", dicomweb.dicomweb_app)
