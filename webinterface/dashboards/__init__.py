from .common import router
from . import query, simple
from starlette.applications import Starlette



dashboards_app = Starlette(routes=router)