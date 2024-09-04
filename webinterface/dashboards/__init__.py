from .common import router
from . import query_routes, simple
from starlette.applications import Starlette



dashboards_app = Starlette(routes=router)