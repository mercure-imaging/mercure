"""
api.py
========
API backend functions for AJAX querying from the web frontend.
"""

# Standard python includes
import daiquiri

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.authentication import requires

# App-specific includes
import common.monitor as monitor


logger = daiquiri.getLogger("api")


###################################################################################
## API endpoints
###################################################################################


api_app = Starlette()


@api_app.route("/get-task-events", methods=["GET"])
@requires(["authenticated"])
async def get_series_events(request):
    logger.debug(request.query_params)
    task_id = request.query_params.get("task_id", "")
    try:
        return JSONResponse(await monitor.get_task_events(task_id))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)


@api_app.route("/get-series", methods=["GET"])
@requires(["authenticated"])
async def get_series(request):
    series_uid = request.query_params.get("series_uid", "")
    try:
        return JSONResponse(await monitor.get_series(series_uid))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)


@api_app.route("/get-tasks", methods=["GET"])
@requires(["authenticated"])
async def get_tasks(request):
    try:
        return JSONResponse(await monitor.get_tasks())
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)

