"""
query.py
========
Entry functions of the bookkeeper for querying processing information.
"""

# Standard python includes
from typing import Any, Dict
from sqlalchemy.engine.base import Connection
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import JSONB
import datetime
import sqlalchemy
import uuid

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.authentication import requires

# App-specific includes
import bookkeeping.config as bk_config
from bookkeeping.database import *
from bookkeeping.helper import *


###################################################################################
## Query endpoints
###################################################################################


query_app = Starlette()


@query_app.route("/series", methods=["GET"])
@requires("authenticated")
async def get_series(request) -> JSONResponse:
    """Endpoint for retrieving series in the database."""
    series_uid = request.query_params.get("series_uid", "")
    query = dicom_series.select()
    if series_uid:
        query = query.where(dicom_series.c.series_uid == series_uid)

    result = await database.fetch_all(query)
    series = [dict(row) for row in result]

    for i, line in enumerate(series):
        series[i] = {
            k: line[k] for k in line if k in ("id", "time", "series_uid", "tag_seriesdescription", "tag_modality")
        }
    return CustomJSONResponse(series)


@query_app.route("/tasks", methods=["GET"])
@requires("authenticated")
async def get_tasks(request) -> JSONResponse:
    """Endpoint for retrieving tasks in the database."""
    query = (
        sqlalchemy.select(
            tasks_table.c.id, tasks_table.c.time, dicom_series.c.tag_seriesdescription, dicom_series.c.tag_modality
        )
        .where(tasks_table.c.parent_id.is_(None))  # only show tasks without parents
        .join(
            dicom_series,
            # sqlalchemy.or_(
            # (dicom_series.c.study_uid == tasks_table.c.study_uid),
            (dicom_series.c.series_uid == tasks_table.c.series_uid),
            # ),
            isouter=True,
        )
    )
    # query = sqlalchemy.text(
    #     """ select tasks.id as task_id, tasks.time, tasks.series_uid, tasks.study_uid, "tag_seriesdescription", "tag_modality" from tasks
    #         join dicom_series on tasks.study_uid = dicom_series.study_uid or tasks.series_uid = dicom_series.series_uid """
    # )
    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


@query_app.route("/tests", methods=["GET"])
@requires("authenticated")
async def get_test_task(request) -> JSONResponse:
    query = tests_table.select().order_by(tests_table.c.time_begin.desc())
    # query = (
    #     sqlalchemy.select(
    #         tasks_table.c.id, tasks_table.c.time, dicom_series.c.tag_seriesdescription, dicom_series.c.tag_modality
    #     )
    #     .join(
    #         dicom_series,
    #         sqlalchemy.or_(
    #             (dicom_series.c.study_uid == tasks_table.c.study_uid),
    #             (dicom_series.c.series_uid == tasks_table.c.series_uid),
    #         ),
    #     )
    #     .where(dicom_series.c.tag_seriesdescription == "self_test_series " + request.query_params.get("id", ""))
    # )
    result_rows = await database.fetch_all(query)
    results = [dict(row) for row in result_rows]
    for k in results:
        if not k["time_end"]:
            if k["time_begin"] < datetime.datetime.now() - datetime.timedelta(minutes=10):
                k["status"] = "failed"
    return CustomJSONResponse(results)


@query_app.route("/task-events", methods=["GET"])
@requires("authenticated")
async def get_task_events(request) -> JSONResponse:
    """Endpoint for getting all events related to one task."""

    # series_uid = request.query_params.get("series_uid", "")
    task_id = request.query_params.get("task_id", "")

    subtask_query = sqlalchemy.select(tasks_table.c.id).where(tasks_table.c.parent_id == task_id)
    subtask_ids = [row[0] for row in await database.fetch_all(subtask_query)]

    # Get all the task_events from task `task_id` or any of its subtasks
    query = (
        task_events.select()
        .order_by(task_events.c.task_id, task_events.c.client_timestamp)
        .where(sqlalchemy.or_(task_events.c.task_id == task_id, task_events.c.task_id.in_(subtask_ids)))
    )

    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


@query_app.route("/dicom-files", methods=["GET"])
@requires("authenticated")
async def get_dicom_files(request) -> JSONResponse:
    """Endpoint for getting all events related to one series."""
    series_uid = request.query_params.get("series_uid", "")
    query = dicom_files.select().order_by(dicom_files.c.time)
    if series_uid:
        query = query.where(dicom_files.c.series_uid == series_uid)
    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


@query_app.route("/find_task", methods=["GET"])
@requires("authenticated")
async def find_task(request) -> JSONResponse:
    search_term = request.query_params.get("search_term", "")

    # query = dicom_series.select()
    # if series_uid:
    #     query = query.where(dicom_series.c.series_uid == series_uid)

    # result = await database.fetch_all(query)
    # series = [dict(row) for row in result]

    # for i, line in enumerate(series):
    #     series[i] = {
    #         k: line[k] for k in line if k in ("id", "time", "series_uid", "tag_seriesdescription", "tag_modality")
    #     }

    response: Dict = {}

    query = sqlalchemy.text(
        """ select tasks.id as task_id, 
        tag_accessionnumber as acc, 
        tag_patientid as mrn,
        data->'info'->'uid_type' as scope
        from tasks
        left join dicom_series on dicom_series.series_uid = tasks.series_uid 
        order by tasks.time desc 
        limit 256 """
    )

    result_rows = await database.fetch_all(query)
    results = [dict(row) for row in result_rows]

    print(results)

    for item in results:
        task_id = item["task_id"]
        acc = item["acc"]
        mrn = item["mrn"]

        if item["scope"] == '"study"':
            job_scope = "STUDY"
        else:
            job_scope = "SERIES"

        status = "Complete"

        response[task_id] = {
            "ACC": acc,
            "MRN": mrn,
            "Scope": job_scope,
            "Status": status,
        }

    return CustomJSONResponse(response)
