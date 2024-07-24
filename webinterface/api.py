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
from decoRouter import Router as decoRouter
router = decoRouter()

logger = daiquiri.getLogger("api")


###################################################################################
## API endpoints
###################################################################################




@router.get("/get-task-events")
@requires(["authenticated"])
async def get_series_events(request):
    logger.debug(request.query_params)
    task_id = request.query_params.get("task_id", "")
    try:
        return JSONResponse(await monitor.get_task_events(task_id))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)


@router.get("/get-series")
@requires(["authenticated"])
async def get_series(request):
    series_uid = request.query_params.get("series_uid", "")
    try:
        return JSONResponse(await monitor.get_series(series_uid))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)


@router.get("/get-tasks")
@requires(["authenticated"])
async def get_tasks(request):
    try:
        return JSONResponse(await monitor.get_tasks())
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)


@router.get("/get-tests")
@requires(["authenticated"])
async def get_tests(request):
    try:
        return JSONResponse(await monitor.get_tests())
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)


@router.get("/find-tasks")
@requires(["authenticated"])
async def find_tasks(request):
    search_term = request.query_params.get("search_term", "")
    study_filter = request.query_params.get("study_filter", "false")
    try:
        return JSONResponse(await monitor.find_tasks(search_term, study_filter))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)


@router.get("/task-process-logs")
@requires(["authenticated"])
async def task_process_logs(request):
    task_id = request.query_params.get("task_id", "")
    try:
        return JSONResponse(await monitor.task_process_logs(task_id))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)


@router.get("/get-task-info")
@requires(["authenticated"])
async def get_task_info(request):
    task_id = request.query_params.get("task_id", "")
    try:
        return JSONResponse(await monitor.get_task_info(task_id))
    except monitor.MonitorHTTPError as e:
        return JSONResponse({"error": e.status_code}, status_code=e.status_code)

api_app = Starlette(routes=router)