from starlette.applications import Starlette

from . import dicomweb, query_routes, simple  # noqa: F401
from .common import router

dashboards_app = Starlette(routes=router)
