"""
query.py
========
Entry functions of the bookkeeper for querying processing information.
"""

# Standard python includes
from typing import Dict
from pathlib import Path
import datetime
import sqlalchemy

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.authentication import requires

# App-specific includes
import bookkeeping.config as bk_config
from bookkeeping.database import *
from bookkeeping.helper import *
from common import config


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
        .order_by(task_events.c.task_id, task_events.c.time)
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


@query_app.route("/task_process_logs", methods=["GET"])
@requires("authenticated")
async def get_task_process_logs(request) -> JSONResponse:
    """Endpoint for getting all events related to one series."""
    task_id = request.query_params.get("task_id", "")

    subtask_query = (
        tasks_table.select()
        .order_by(tasks_table.c.id)
        .where(sqlalchemy.or_(tasks_table.c.id == task_id, tasks_table.c.parent_id == task_id))
    )

    subtasks = await database.fetch_all(subtask_query)
    subtask_ids = [row[0] for row in subtasks]

    query = processor_logs_table.select(processor_logs_table.c.task_id.in_(subtask_ids))
    results = [dict(r) for r in await database.fetch_all(query)]
    for result in results:
        if result["logs"] == None:
            if logs_folder := config.mercure.processing_logs.logs_file_store:
                result["logs"] = (
                    Path(logs_folder) / result["task_id"] / f"{result['module_name']}.{result['id']}.txt"
                ).read_text(encoding="utf-8")
    return CustomJSONResponse(results)


@query_app.route("/find_task", methods=["GET"])
@requires("authenticated")
async def find_task(request) -> JSONResponse:
    search_term = request.query_params.get("search_term", "")
    filter_term = ""
    if search_term:
        filter_term = f"""and ((tag_accessionnumber ilike '{search_term}%') or (tag_patientid ilike '{search_term}%') or (tag_patientname ilike '%{search_term}%'))"""

    query = sqlalchemy.text(
        f""" select tasks.id as task_id, 
        tag_accessionnumber as acc, 
        tag_patientid as mrn,
        data->'info'->>'uid_type' as scope,
        tasks.time as time
        from tasks
        left join dicom_series on dicom_series.series_uid = tasks.series_uid 
        where parent_id is null {filter_term}
        order by date_trunc('second', tasks.time) desc, tasks.id desc
        limit 256 """
    )

    response: Dict = {}
    result_rows = await database.fetch_all(query)
    results = [dict(row) for row in result_rows]

    for item in results:
        task_id = item["task_id"]
        time = item["time"]
        acc = item["acc"]
        mrn = item["mrn"]

        if item["scope"] == "study":
            job_scope = "STUDY"
        else:
            job_scope = "SERIES"

        response[task_id] = {
            "ACC": acc,
            "MRN": mrn,
            "Scope": job_scope,
            "Time": time,
        }

    return CustomJSONResponse(response)


@query_app.route("/get_task_info", methods=["GET"])
@requires("authenticated")
async def get_task_info(request) -> JSONResponse:
    response: Dict = {}

    task_id = request.query_params.get("task_id", "")
    if not task_id:
        return CustomJSONResponse(response)

    # First, get general information about the series/study
    info_query = sqlalchemy.text(
        f"""select 
        dicom_series.tag_patientname as patientname,
        dicom_series.tag_patientbirthdate as birthdate,
        dicom_series.tag_patientsex as gender,
        dicom_series.tag_modality as modality,
        dicom_series.tag_acquisitiondate as acquisitiondate,
        dicom_series.tag_acquisitiontime as acquisitiontime,
        dicom_series.tag_bodypartexamined as bodypartexamined,
        dicom_series.tag_studydescription as studydescription,
        dicom_series.tag_protocolname as protocolname,
        dicom_series.tag_manufacturer as manufacturer,
        dicom_series.tag_manufacturermodelname as manufacturermodelname,
        dicom_series.tag_deviceserialnumber as deviceserialnumber,
        dicom_series.tag_magneticfieldstrength as magneticfieldstrength
        from tasks
        left join dicom_series on dicom_series.series_uid = tasks.series_uid 
        where (tasks.id = '{task_id}') and (tasks.parent_id is null)
        limit 1"""
    ) # TODO: use sqlalchemy interpolation

    info_rows = await database.fetch_all(info_query)
    info_results = [dict(row) for row in info_rows]

    if info_results:
        response["information"] = {
            "patient_name": info_results[0]["patientname"],
            "patient_birthdate": info_results[0]["birthdate"],
            "patient_sex": info_results[0]["gender"],
            "acquisition_date": info_results[0]["acquisitiondate"],
            "acquisition_time": info_results[0]["acquisitiontime"],
            "modality": info_results[0]["modality"],
            "bodypart_examined": info_results[0]["bodypartexamined"],
            "study_description": info_results[0]["studydescription"],
            "protocol_name": info_results[0]["protocolname"],
            "manufacturer": info_results[0]["manufacturer"],
            "manufacturer_modelname": info_results[0]["manufacturermodelname"],
            "device_serialnumber": info_results[0]["deviceserialnumber"],
            "magnetic_fieldstrength": info_results[0]["magneticfieldstrength"],
        }

    # Now, get the task files embedded into the task or its subtasks
    query = (
        tasks_table.select()
        .order_by(tasks_table.c.id)
        .where(sqlalchemy.or_(tasks_table.c.id == task_id, tasks_table.c.parent_id == task_id))
    )
    result_rows = await database.fetch_all(query)
    results = [dict(row) for row in result_rows]

    for item in results:
        if item["data"]:
            task_id = "task " + item["id"]
            response[task_id] = item["data"]

    return CustomJSONResponse(response)
