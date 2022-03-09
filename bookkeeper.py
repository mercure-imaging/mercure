"""
bookkeeper.py
=============
The bookkeeper service of mercure, which receives notifications from all mercure services
and stores the information in a Postgres database.
"""
# Standard python includes
import os
import sys
from typing import Any
import asyncpg
from sqlalchemy.engine.base import Connection
from sqlalchemy.dialects.postgresql import JSONB
import uvicorn
import datetime
import daiquiri
import databases
import sqlalchemy
import hupper
import json

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import Response, JSONResponse


from starlette.background import BackgroundTasks
from starlette.config import Config
from starlette.datastructures import URL
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from starlette_auth_toolkit.base.backends import BaseTokenAuth
from starlette.authentication import requires
from starlette.authentication import SimpleUser

# App-specific includes
import common.monitor as monitor
from common.constants import mercure_defs
from common import config


###################################################################################
## Configuration and initialization
###################################################################################

daiquiri.setup(
    config.get_loglevel(),
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt=config.get_logformat()
            )
        ),
    ),
)
logger = daiquiri.getLogger("bookkeeper")


bookkeeper_config = Config((os.getenv("MERCURE_CONFIG_FOLDER") or "/opt/mercure/config") + "/bookkeeper.env")

BOOKKEEPER_PORT = bookkeeper_config("PORT", cast=int, default=8080)
BOOKKEEPER_HOST = bookkeeper_config("HOST", default="0.0.0.0")
DATABASE_URL = bookkeeper_config("DATABASE_URL", default="postgresql://mercure@localhost")
DATABASE_SCHEMA = bookkeeper_config("DATABASE_SCHEMA", default=None)
DEBUG_MODE = bookkeeper_config("DEBUG", cast=bool, default=False)
API_KEY = None


def set_api_key() -> None:
    global API_KEY
    if API_KEY is None:
        from common.config import read_config

        try:
            c = read_config()
            API_KEY = c.bookkeeper_api_key
            if not API_KEY or API_KEY == "BOOKKEEPER_TOKEN_PLACEHOLDER":
                raise Exception("No API key set in config.json. Bookkeeper cannot function.")
        except (ResourceWarning, FileNotFoundError) as e:
            raise e


class TokenAuth(BaseTokenAuth):
    async def verify(self, token: str):
        if API_KEY is None:
            logger.error("API key not set")
            return None
        if token != API_KEY:
            return None
        return SimpleUser("user")


database = databases.Database(DATABASE_URL)

app = Starlette(debug=DEBUG_MODE)

app.add_middleware(
    AuthenticationMiddleware,
    backend=TokenAuth(),
    on_error=lambda _, exc: PlainTextResponse(str(exc), status_code=401),
)

###################################################################################
## Definition of database tables
###################################################################################

metadata = sqlalchemy.MetaData(schema=DATABASE_SCHEMA)

mercure_events = sqlalchemy.Table(
    "mercure_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.String, default=monitor.m_events.UNKNOWN),
    sqlalchemy.Column("severity", sqlalchemy.Integer, default=monitor.severity.INFO),
    sqlalchemy.Column("description", sqlalchemy.String, default=""),
)

webgui_events = sqlalchemy.Table(
    "webgui_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.String, default=monitor.w_events.UNKNOWN),
    sqlalchemy.Column("user", sqlalchemy.String, default=""),
    sqlalchemy.Column("description", sqlalchemy.String, default=""),
)

dicom_files = sqlalchemy.Table(
    "dicom_files",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("filename", sqlalchemy.String),
    sqlalchemy.Column("file_uid", sqlalchemy.String),
    sqlalchemy.Column("series_uid", sqlalchemy.String),
)

dicom_series = sqlalchemy.Table(
    "dicom_series",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("series_uid", sqlalchemy.String, unique=True),
    sqlalchemy.Column("study_uid", sqlalchemy.String),
    sqlalchemy.Column("tag_patientname", sqlalchemy.String),
    sqlalchemy.Column("tag_patientid", sqlalchemy.String),
    sqlalchemy.Column("tag_accessionnumber", sqlalchemy.String),
    sqlalchemy.Column("tag_seriesnumber", sqlalchemy.String),
    sqlalchemy.Column("tag_studyid", sqlalchemy.String),
    sqlalchemy.Column("tag_patientbirthdate", sqlalchemy.String),
    sqlalchemy.Column("tag_patientsex", sqlalchemy.String),
    sqlalchemy.Column("tag_acquisitiondate", sqlalchemy.String),
    sqlalchemy.Column("tag_acquisitiontime", sqlalchemy.String),
    sqlalchemy.Column("tag_modality", sqlalchemy.String),
    sqlalchemy.Column("tag_bodypartexamined", sqlalchemy.String),
    sqlalchemy.Column("tag_studydescription", sqlalchemy.String),
    sqlalchemy.Column("tag_seriesdescription", sqlalchemy.String),
    sqlalchemy.Column("tag_protocolname", sqlalchemy.String),
    sqlalchemy.Column("tag_codevalue", sqlalchemy.String),
    sqlalchemy.Column("tag_codemeaning", sqlalchemy.String),
    sqlalchemy.Column("tag_sequencename", sqlalchemy.String),
    sqlalchemy.Column("tag_scanningsequence", sqlalchemy.String),
    sqlalchemy.Column("tag_sequencevariant", sqlalchemy.String),
    sqlalchemy.Column("tag_slicethickness", sqlalchemy.String),
    sqlalchemy.Column("tag_contrastbolusagent", sqlalchemy.String),
    sqlalchemy.Column("tag_referringphysicianname", sqlalchemy.String),
    sqlalchemy.Column("tag_manufacturer", sqlalchemy.String),
    sqlalchemy.Column("tag_manufacturermodelname", sqlalchemy.String),
    sqlalchemy.Column("tag_magneticfieldstrength", sqlalchemy.String),
    sqlalchemy.Column("tag_deviceserialnumber", sqlalchemy.String),
    sqlalchemy.Column("tag_softwareversions", sqlalchemy.String),
    sqlalchemy.Column("tag_stationname", sqlalchemy.String),
)

task_events = sqlalchemy.Table(
    "task_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("task_id", sqlalchemy.String, sqlalchemy.ForeignKey("tasks.id"), nullable=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.String),
    # sqlalchemy.Column("series_uid", sqlalchemy.String),
    sqlalchemy.Column("file_count", sqlalchemy.Integer),
    sqlalchemy.Column("target", sqlalchemy.String),
    sqlalchemy.Column("info", sqlalchemy.String),
)

file_events = sqlalchemy.Table(
    "file_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("dicom_file", sqlalchemy.Integer),
    sqlalchemy.Column("event", sqlalchemy.Integer),
)

dicom_series_map = sqlalchemy.Table(
    "dicom_series_map",
    metadata,
    sqlalchemy.Column("id_file", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("id_series", sqlalchemy.Integer),
)

series_sequence_data = sqlalchemy.Table(
    "series_sequence_data",
    metadata,
    sqlalchemy.Column("uid", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
)

tasks_table = sqlalchemy.Table(
    "tasks",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("series_uid", sqlalchemy.String),
    sqlalchemy.Column("study_uid", sqlalchemy.String),
    sqlalchemy.Column("data", JSONB),
)


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(obj, datetime.date):
            return obj.strftime("%Y-%m-%d")
        else:
            try:
                dict_ = dict(obj)
            except TypeError:
                pass
            else:
                return dict_
            return super(CustomJSONEncoder, self).default(obj)


class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, cls=CustomJSONEncoder).encode("utf-8")


###################################################################################
## Event handlers
###################################################################################


def create_database() -> None:
    """Creates all tables in the database if they do not exist."""
    metadata.create_all(sqlalchemy.create_engine(DATABASE_URL).connect())


@app.on_event("startup")
async def startup() -> None:
    """Connects to database on startup. If the database does not exist, it will
    be created."""
    await database.connect()
    create_database()
    set_api_key()


@app.on_event("shutdown")
async def shutdown() -> None:
    """Disconnect from database on shutdown."""
    await database.disconnect()


###################################################################################
## Endpoints
###################################################################################


# async def execute_db_operation(operation) -> None:
#     global connection
#     """Executes a previously prepared database operation."""
#     try:
#         connection.execute(operation)
#     except:
#         pass


@app.route("/test", methods=["GET", "POST"])
async def test_endpoint(request) -> JSONResponse:
    """Endpoint for testing that the bookkeeper is active."""
    return JSONResponse({"ok": ""})


@app.route("/mercure-event", methods=["POST"])
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


@app.route("/webgui-event", methods=["POST"])
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


@app.route("/register-dicom", methods=["POST"])
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


@app.route("/register-series", methods=["POST"])
@requires("authenticated")
async def register_series(request) -> JSONResponse:
    """Endpoint that is called by the router whenever a new series arrives."""
    payload = dict(await request.form())
    try:
        await parse_and_submit_tags(payload)
    except asyncpg.exceptions.UniqueViolationError:
        logger.debug("Series already registered.")

    return JSONResponse({"ok": ""})


@app.route("/register-task", methods=["POST"])
@requires("authenticated")
async def register_task(request) -> JSONResponse:
    """Endpoint that is called by the router whenever a new series arrives."""
    payload = dict(await request.json())
    series_uid = None
    study_uid = None
    logger.debug(payload)
    id = payload["id"]
    if payload["info"]["uid_type"] == "series":
        series_uid = payload["info"]["uid"]
    if payload["info"]["uid_type"] == "study":
        study_uid = payload["info"]["uid"]
    data = await request.json()

    query = tasks_table.insert().values(
        id=id, series_uid=series_uid, study_uid=study_uid, time=datetime.datetime.now(), data=data
    )
    await database.execute(query)
    return JSONResponse({"ok": ""})


@app.route("/task-event", methods=["POST"])
@requires("authenticated")
async def post_task_event(request) -> JSONResponse:
    """Endpoint for logging all events related to one series."""
    payload = dict(await request.form())
    sender = payload.get("sender", "Unknown")
    event = payload.get("event", monitor.s_events.UNKNOWN)
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
        time=datetime.datetime.now(),
    )
    await database.execute(query)
    return JSONResponse({"ok": ""})


@app.route("/series", methods=["GET"])
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


@app.route("/tasks", methods=["GET"])
@requires("authenticated")
async def get_tasks(request) -> JSONResponse:
    """Endpoint for retrieving tasks in the database."""
    query = sqlalchemy.select(
        tasks_table.c.id, tasks_table.c.time, dicom_series.c.tag_seriesdescription, dicom_series.c.tag_modality
    ).join(
        dicom_series,
        sqlalchemy.or_(
            (dicom_series.c.study_uid == tasks_table.c.study_uid),
            (dicom_series.c.series_uid == tasks_table.c.series_uid),
        ),
    )
    # query = sqlalchemy.text(
    #     """ select tasks.id as task_id, tasks.time, tasks.series_uid, tasks.study_uid, "tag_seriesdescription", "tag_modality" from tasks
    #         join dicom_series on tasks.study_uid = dicom_series.study_uid or tasks.series_uid = dicom_series.series_uid """
    # )
    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


@app.route("/task-events", methods=["GET"])
@requires("authenticated")
async def get_task_events(request) -> JSONResponse:
    """Endpoint for getting all events related to one series."""

    # series_uid = request.query_params.get("series_uid", "")
    task_id = request.query_params.get("task_id", "")

    query = task_events.select().order_by(task_events.c.time)
    # if series_uid:
    #     query = query.where(series_events.c.series_uid == series_uid)
    # elif task_id:
    query = query.where(task_events.c.task_id == task_id)
    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


@app.route("/dicom-files", methods=["GET"])
@requires("authenticated")
async def get_dicom_files(request) -> JSONResponse:
    """Endpoint for getting all events related to one series."""
    series_uid = request.query_params.get("series_uid", "")
    query = dicom_files.select().order_by(dicom_files.c.time)
    if series_uid:
        query = query.where(dicom_files.c.series_uid == series_uid)
    results = await database.fetch_all(query)
    return CustomJSONResponse(results)


###################################################################################
## Main entry function
###################################################################################
@app.exception_handler(500)
async def server_error(request, exc) -> Response:
    """
    Return an HTTP 500 page.
    """
    return JSONResponse({"error": "Internal server error"}, status_code=500)


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

    uvicorn.run(app, host=BOOKKEEPER_HOST, port=BOOKKEEPER_PORT)


if __name__ == "__main__":
    main()
