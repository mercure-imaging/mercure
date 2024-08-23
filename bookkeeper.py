"""
bookkeeper.py
=============
The bookkeeper service of mercure, which receives notifications from all mercure services
and stores the information in a Postgres database.
"""

# Standard python includes
import contextlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Union
import asyncpg
from sqlalchemy.dialects.postgresql import insert
import uvicorn
import datetime
import daiquiri
import hupper

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette_auth_toolkit.base.backends import BaseTokenAuth
from starlette.authentication import requires
from starlette.authentication import SimpleUser

# App-specific includes
from common import config
import common.monitor as monitor
from common.constants import mercure_defs
from bookkeeping.database import *
import bookkeeping.query as query
import bookkeeping.config as bk_config
from decoRouter import Router as decoRouter
router = decoRouter()

###################################################################################
## Configuration and initialization
###################################################################################


logger = config.get_logger()


class TokenAuth(BaseTokenAuth):
    async def verify(self, token: str):
        global API_KEY
        if bk_config.API_KEY is None:
            logger.error("API key not set")
            return None
        if token != bk_config.API_KEY:
            return None
        return SimpleUser("user")



###################################################################################
## Event handlers
###################################################################################


def create_database() -> None:
    """Creates all tables in the database if they do not exist."""
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        env={
            **os.environ,
            "PATH": "/opt/mercure/env/bin:" + os.environ["PATH"],
            "DATABASE_URL": bk_config.DATABASE_URL,
        },
    )



###################################################################################
## Endpoints for event submission
###################################################################################

# async def execute_db_operation(operation) -> None:
#     global connection
#     """Executes a previously prepared database operation."""
#     try:
#         connection.execute(operation)
#     except:
#         pass

@router.post()
@router.get("/test")
async def test_endpoint(request) -> JSONResponse:
    """Endpoint for testing that the bookkeeper is active."""
    return JSONResponse({"ok": ""})


@router.post("/mercure-event")
@requires("authenticated")
async def post_mercure_event(request) -> JSONResponse:
    """Endpoint for receiving mercure system events."""
    payload = dict(await request.form())
    sender = payload.get("sender", "Unknown")
    event = payload.get("event", monitor.m_events.UNKNOWN)
    severity = int(payload.get("severity", monitor.severity.INFO))
    description = payload.get("description", "")

    query = mercure_events.insert().values(
        sender=sender, event=event, severity=severity, description=description, time=datetime.datetime.now()
    )
    result = await database.execute(query)
    logger.debug(result)
    return JSONResponse({"ok": ""})


@router.post("/processor-logs")
@requires("authenticated")
async def processor_logs(request) -> JSONResponse:
    """Endpoint for receiving mercure system events."""
    payload = dict(await request.form())

    try:
        task_id = payload["task_id"]
    except IndexError:
        return JSONResponse({"error": "no task_id supplied"}, 400)
    try:
        module_name = payload["module_name"]
    except IndexError:
        return JSONResponse({"error": "no module_name supplied"}, 400)

    time = datetime.datetime.now()
    try:
        logs = str(payload.get("logs", ""))
    except:
        return JSONResponse({"error": "unable to read logs"}, 400)

    if (logs_folder_str := config.mercure.processing_logs.logs_file_store) and (
        logs_path := Path(logs_folder_str)
    ).exists():
        query = processor_logs_table.insert().values(task_id=task_id, module_name=module_name, time=time, logs=None)
        result = await database.execute(query)

        logs_path = logs_path / task_id
        logs_path.mkdir(exist_ok=True)
        logs_file = logs_path / f"{module_name}.{str(result)}.txt"
        logs_file.write_text(logs, encoding="utf-8")
    else:
        query = processor_logs_table.insert().values(task_id=task_id, module_name=module_name, time=time, logs=logs)
        result = await database.execute(query)

    logger.debug(result)
    return JSONResponse({"ok": ""})


@router.post("/webgui-event")
@requires("authenticated")
async def post_webgui_event(request) -> JSONResponse:
    """Endpoint for logging relevant events of the webgui."""
    payload = dict(await request.form())
    sender = payload.get("sender", "Unknown")
    event = payload.get("event", monitor.w_events.UNKNOWN)
    user = payload.get("user", "UNKNOWN")
    description = payload.get("description", "")

    query = webgui_events.insert().values(
        sender=sender, event=event, user=user, description=description, time=datetime.datetime.now()
    )
    await database.execute(query)
    # tasks = BackgroundTasks()
    # tasks.add_task(execute_db_operation, operation=query)
    return JSONResponse({"ok": ""})


@router.post("/register-dicom")
@requires("authenticated")
async def register_dicom(request) -> JSONResponse:
    """Endpoint for registering newly received DICOM files. Called by the getdcmtags module."""
    payload = dict(await request.form())
    filename = payload.get("filename", "")
    file_uid = payload.get("file_uid", "")
    series_uid = payload.get("series_uid", "")

    query = dicom_files.insert().values(
        filename=filename, file_uid=file_uid, series_uid=series_uid, time=datetime.datetime.now()
    )
    result = await database.execute(query)
    logger.debug(f"Result: {result}")

    # tasks = BackgroundTasks()
    # tasks.add_task(execute_db_operation, operation=query)
    return JSONResponse({"ok": ""})


async def parse_and_submit_tags(payload) -> None:
    """Helper function that reads series information from the request body."""
    query = dicom_series.insert().values(
        time=datetime.datetime.now(),
        series_uid=payload.get("SeriesInstanceUID", ""),
        study_uid=payload.get("StudyInstanceUID", ""),
        tag_patientname=payload.get("PatientName", ""),
        tag_patientid=payload.get("PatientID", ""),
        tag_accessionnumber=payload.get("AccessionNumber", ""),
        tag_seriesnumber=payload.get("SeriesNumber", ""),
        tag_studyid=payload.get("StudyID", ""),
        tag_patientbirthdate=payload.get("PatientBirthDate", ""),
        tag_patientsex=payload.get("PatientSex", ""),
        tag_acquisitiondate=payload.get("AcquisitionDate", ""),
        tag_acquisitiontime=payload.get("AcquisitionTime", ""),
        tag_modality=payload.get("Modality", ""),
        tag_bodypartexamined=payload.get("BodyPartExamined", ""),
        tag_studydescription=payload.get("StudyDescription", ""),
        tag_seriesdescription=payload.get("SeriesDescription", ""),
        tag_protocolname=payload.get("ProtocolName", ""),
        tag_codevalue=payload.get("CodeValue", ""),
        tag_codemeaning=payload.get("CodeMeaning", ""),
        tag_sequencename=payload.get("SequenceName", ""),
        tag_scanningsequence=payload.get("ScanningSequence", ""),
        tag_sequencevariant=payload.get("SequenceVariant", ""),
        tag_slicethickness=payload.get("SliceThickness", ""),
        tag_contrastbolusagent=payload.get("ContrastBolusAgent", ""),
        tag_referringphysicianname=payload.get("ReferringPhysicianName", ""),
        tag_manufacturer=payload.get("Manufacturer", ""),
        tag_manufacturermodelname=payload.get("ManufacturerModelName", ""),
        tag_magneticfieldstrength=payload.get("MagneticFieldStrength", ""),
        tag_deviceserialnumber=payload.get("DeviceSerialNumber", ""),
        tag_softwareversions=payload.get("SoftwareVersions", ""),
        tag_stationname=payload.get("StationName", ""),
    )
    await database.execute(query)


@router.post("/register-series")
@requires("authenticated")
async def register_series(request) -> JSONResponse:
    """Endpoint that is called by the router whenever a new series arrives."""
    payload = dict(await request.form())
    try:
        await parse_and_submit_tags(payload)
    except asyncpg.exceptions.UniqueViolationError:
        logger.debug("Series already registered.", exc_info=None)

    return JSONResponse({"ok": ""})


@router.post("/register-task")
@requires("authenticated")
async def register_task(request) -> JSONResponse:
    payload = dict(await request.json())

    # Registering the task ordinarily happens first, but if "update-task"
    # came in first, we need to update the task instead. So we do an upsert.
    query = (
        insert(tasks_table)
        .values(
            id=payload["id"],
            series_uid=payload["series_uid"],
            parent_id=payload.get("parent_id"),
            time=datetime.datetime.now(),
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "series_uid": payload["series_uid"],
                "parent_id": payload.get("parent_id"),
            },
        )
    )

    await database.execute(query)
    return JSONResponse({"ok": ""})


@router.post("/update-task")
@requires("authenticated")
async def update_task(request) -> JSONResponse:
    """Endpoint that is called by the router whenever a new series arrives."""
    data = await request.json()
    payload = dict(data)
    logger.debug(payload)

    study_uid = None
    update_values = dict(id=payload["id"], time=datetime.datetime.now(), data=data)

    if "info" in payload:
        if payload["info"]["uid_type"] == "study":
            study_uid = payload["info"]["uid"]
            series_uid = payload["study"]["received_series_uid"][0]
            update_values["study_uid"] = study_uid
            update_values["series_uid"] = series_uid
        if payload["info"]["uid_type"] == "series":
            series_uid = payload["info"]["uid"]
            update_values["series_uid"] = series_uid

    # Ordinarily, update-task is called on an existing task. But if the task is
    # not yet registered, we need to create it. So we use an upsert here.
    query = (
        insert(tasks_table)
        .values(**update_values)
        .on_conflict_do_update(  # update if exists
            index_elements=["id"],
            set_=update_values,
        )
    )
    await database.execute(query)
    return JSONResponse({"ok": ""})


@router.post("/test-begin")
@requires("authenticated")
async def test_begin(request) -> JSONResponse:
    payload = dict(await request.json())
    id = payload["id"]
    type = payload.get("type", "route")
    rule_type = payload.get("rule_type", "series")
    task_id = payload.get("task_id", None)
    query_a = insert(tests_table).values(
        id=id, time_begin=datetime.datetime.now(), type=type, status="begin", task_id=task_id, rule_type=rule_type
    )

    query = query_a.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "task_id": task_id or query_a.excluded.task_id,
        },
    )
    await database.execute(query)
    return JSONResponse({"ok": ""})


@router.post("/test-end")
@requires("authenticated")
async def test_end(request) -> JSONResponse:
    payload = dict(await request.json())
    id = payload["id"]
    status = payload.get("status", "")

    query = tests_table.update(tests_table.c.id == id).values(time_end=datetime.datetime.now(), status=status)
    await database.execute(query)
    return JSONResponse({"ok": ""})


@router.post("/task-event")
@requires("authenticated")
async def post_task_event(request) -> JSONResponse:
    """Endpoint for logging all events related to one series."""
    payload = dict(await request.form())
    sender = payload.get("sender", "Unknown")
    event = payload.get("event", monitor.task_event.UNKNOWN)
    client_timestamp = None
    event_time = datetime.datetime.now()

    if "timestamp" in payload:
        try:
            client_timestamp = float(payload.get("timestamp"))  # type: ignore
        except:
            pass

    if "time" in payload:
        try:
            event_time = datetime.datetime.fromisoformat(payload.get("time"))  # type: ignore
        except:
            pass

    # series_uid = payload.get("series_uid", "")
    try:
        file_count = int(payload.get("file_count", 0))
    except ValueError:
        file_count = 0

    file_count = int(file_count)
    target = payload.get("target", "")
    info = payload.get("info", "")
    task_id = payload.get("task_id")

    query = task_events.insert().values(
        sender=sender,
        event=event,
        task_id=task_id,
        # series_uid=None,
        file_count=file_count,
        target=target,
        info=info,
        time=event_time,
        client_timestamp=client_timestamp,
    )
    await database.execute(query)
    return JSONResponse({"ok": ""})


@router.post("/store-processor-output")
@requires("authenticated")
async def store_processor_output(request) -> JSONResponse:
    payload = dict(await request.json())
    values_dict = {k:payload[k] for k in ("task_id", "task_acc", "task_mrn", "module", "index", "settings", "output")}
    query = processor_outputs_table.insert().values(**values_dict)
    await database.execute(query)
    return JSONResponse({"ok": ""})


###################################################################################
## Main entry function
###################################################################################


@contextlib.asynccontextmanager
async def lifespan(app):
    await database.connect()
    create_database()
    bk_config.set_api_key()
    yield
    await database.disconnect()


async def server_error(request, exc) -> Response:
    """
    Return an HTTP 500 page.
    """
    return JSONResponse({"error": "Internal server error"}, status_code=500)

exception_handlers = {
    500: server_error
}


app = Starlette(debug=bk_config.DEBUG_MODE, routes=router, lifespan=lifespan, exception_handlers=exception_handlers)
app.add_middleware(
    AuthenticationMiddleware,
    backend=TokenAuth(),
    on_error=lambda _, exc: PlainTextResponse(str(exc), status_code=401),
)
app.mount("/query", query.query_app)

def main(args=sys.argv[1:]) -> None:
    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        reloader = hupper.start_reloader("bookkeeper.main")
        import logging

        logging.getLogger("multipart.multipart").setLevel(logging.WARNING)

    logger.info("")
    logger.info(f"mercure Bookkeeper ver {mercure_defs.VERSION}")
    logger.info("--------------------------------------------")
    logger.info("")

    try:
        config.read_config()
        query.set_timezone_conversion()
    except Exception as e:
        logger.error(f"Could not read configuration file: {e}")
        logger.info("Going down.")
        sys.exit(1)

    uvicorn.run(app, host=bk_config.BOOKKEEPER_HOST, port=bk_config.BOOKKEEPER_PORT)


if __name__ == "__main__":
    main()
