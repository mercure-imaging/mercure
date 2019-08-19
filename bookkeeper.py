#!/usr/bin/python

# Standard python includes
import uvicorn
import datetime
import logging

# 3rd party
import daiquiri
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.background import BackgroundTasks
from starlette.config import Config
from starlette.datastructures import URL, Secret
import databases
import sqlalchemy
 
# App-specific includes
import common.monitor as monitor

hermes_bookkeeper_version = "0.1a"


###################################################################################
## Configuration and initialization
###################################################################################

daiquiri.setup(
    level=logging.INFO,
    outputs=(
        daiquiri.output.Stream(
            formatter=daiquiri.formatter.ColorFormatter(
                fmt="%(color)s%(levelname)-8.8s "
                "%(name)s: %(message)s%(color_stop)s"
            )
        ),
    ),
)
logger = daiquiri.getLogger("bookkeeper")


bookkeeper_config = Config("configuration/bookkeeper.env")
BOOKKEEPER_PORT   = bookkeeper_config('PORT', cast=int, default=8080)
BOOKKEEPER_HOST   = bookkeeper_config('HOST', default='0.0.0.0')
DATABASE_URL      = bookkeeper_config('DATABASE_URL')

database = databases.Database(DATABASE_URL)
app = Starlette(debug=True)


###################################################################################
## Definition of database tables
###################################################################################

metadata = sqlalchemy.MetaData()
engine = sqlalchemy.create_engine(DATABASE_URL)
connection = None

hermes_events = sqlalchemy.Table(
    "hermes_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.String, default=monitor.h_events.UKNOWN),
    sqlalchemy.Column("severity", sqlalchemy.Integer, default=monitor.severity.INFO),
    sqlalchemy.Column("description", sqlalchemy.String, default="")
)

webgui_events = sqlalchemy.Table(
    "webgui_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.String, default=monitor.w_events.UKNOWN),
    sqlalchemy.Column("user", sqlalchemy.String, default=""),
    sqlalchemy.Column("description", sqlalchemy.String, default="")
)

dicom_files = sqlalchemy.Table(
    "dicom_files",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("filename", sqlalchemy.String),
    sqlalchemy.Column("file_uid", sqlalchemy.String),
    sqlalchemy.Column("series_uid", sqlalchemy.String)
)

dicom_series = sqlalchemy.Table(
    "dicom_series",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("series_uid", sqlalchemy.String, unique=True),
    sqlalchemy.Column("tag_patienname", sqlalchemy.String),
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
    sqlalchemy.Column("tag_stationname", sqlalchemy.String)
)

series_events = sqlalchemy.Table(
    "series_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),    
    sqlalchemy.Column("event", sqlalchemy.String),
    sqlalchemy.Column("series_uid", sqlalchemy.String),
    sqlalchemy.Column("file_count", sqlalchemy.Integer),
    sqlalchemy.Column("target", sqlalchemy.String),    
    sqlalchemy.Column("info", sqlalchemy.String)
)

file_events = sqlalchemy.Table(
    "file_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("dicom_file", sqlalchemy.Integer),
    sqlalchemy.Column("event", sqlalchemy.Integer)
)

dicom_series_map = sqlalchemy.Table(
    "dicom_series_map",
    metadata,
    sqlalchemy.Column("id_file", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("id_series", sqlalchemy.Integer)
)


###################################################################################
## Event handlers
###################################################################################

def create_database():
    metadata.create_all(engine)


@app.on_event("startup")
async def startup():
    global connection
    connection = engine.connect()
    create_database()


@app.on_event("shutdown")
async def shutdown():
    engine.disconnect()


###################################################################################
## Endpoints
###################################################################################

async def execute_db_operation(operation):
    try:
        connection.execute(operation)
    except:
        pass


@app.route('/test', methods=["GET","POST"])
async def test_endpoint(request):
    return JSONResponse({'ok': ''})


@app.route('/hermes-event', methods=["POST"])
async def post_hermes_event(request):
    payload     = dict(await request.form())
    sender      = payload.get("sender","Unknown")
    event       = payload.get("event",monitor.h_events.UKNOWN)
    severity    = int(payload.get("severity",monitor.severity.INFO))    
    description = payload.get("description","")       

    query = hermes_events.insert().values(
        sender=sender, event=event, severity=severity, description=description, time=datetime.datetime.now()
    )
    tasks = BackgroundTasks()
    tasks.add_task(execute_db_operation, operation=query)
    return JSONResponse({'ok': ''}, background=tasks)


@app.route('/webgui-event', methods=["POST"])
async def post_webgui_event(request):
    payload     = dict(await request.form())
    sender      = payload.get("sender","Unknown")
    event       = payload.get("event",monitor.w_events.UKNOWN)
    user        = payload.get("user","UNKNOWN")
    description = payload.get("description","")       

    query = webgui_events.insert().values(
        sender=sender, event=event, user=user, description=description, time=datetime.datetime.now()
    )
    tasks = BackgroundTasks()
    tasks.add_task(execute_db_operation, operation=query)
    return JSONResponse({'ok': ''}, background=tasks)

    
@app.route('/register-dicom', methods=["POST"])
async def register_dicom(request):
    payload    = dict(await request.form())
    filename   = payload.get("filename","")
    file_uid   = payload.get("file_uid","")
    series_uid = payload.get("series_uid","")

    query = dicom_files.insert().values(
        filename=filename, file_uid=file_uid, series_uid=series_uid, time=datetime.datetime.now()
    )
    tasks = BackgroundTasks()
    tasks.add_task(execute_db_operation, operation=query)    
    return JSONResponse({'ok': ''}, background=tasks)


async def parse_and_submit_tags(payload):
    try:
        query = dicom_series.insert().values(
            time                      =datetime.datetime.now(), 
            series_uid                =payload.get("SeriesInstanceUID",""),
            tag_patienname            =payload.get("PatientName",""),
            tag_patientid             =payload.get("PatientID",""),
            tag_accessionnumber       =payload.get("AccessionNumber",""),
            tag_seriesnumber          =payload.get("SeriesNumber",""),
            tag_studyid               =payload.get("StudyID",""),
            tag_patientbirthdate      =payload.get("PatientBirthDate",""),
            tag_patientsex            =payload.get("PatientSex",""),
            tag_acquisitiondate       =payload.get("AcquisitionDate",""),
            tag_acquisitiontime       =payload.get("AcquisitionTime",""),
            tag_modality              =payload.get("Modality",""),
            tag_bodypartexamined      =payload.get("BodyPartExamined",""),
            tag_studydescription      =payload.get("StudyDescription",""),
            tag_seriesdescription     =payload.get("SeriesDescription",""),
            tag_protocolname          =payload.get("ProtocolName",""),
            tag_codevalue             =payload.get("CodeValue",""),
            tag_codemeaning           =payload.get("CodeMeaning",""),
            tag_sequencename          =payload.get("SequenceName",""),
            tag_scanningsequence      =payload.get("ScanningSequence",""),
            tag_sequencevariant       =payload.get("SequenceVariant",""),
            tag_slicethickness        =payload.get("SliceThickness",""),
            tag_contrastbolusagent    =payload.get("ContrastBolusAgent",""),
            tag_referringphysicianname=payload.get("ReferringPhysicianName",""),
            tag_manufacturer          =payload.get("Manufacturer",""),
            tag_manufacturermodelname =payload.get("ManufacturerModelName",""),
            tag_magneticfieldstrength =payload.get("MagneticFieldStrength",""),
            tag_deviceserialnumber    =payload.get("DeviceSerialNumber",""),
            tag_softwareversions      =payload.get("SoftwareVersions",""),
            tag_stationname           =payload.get("StationName","")
        )
        connection.execute(query)
    except Exception as e:
        print(e)
        # TODO: Implement differentiation between IntegrityError and other exceptions
        pass


@app.route('/register-series', methods=["POST"])
async def register_series(request):
    payload = dict(await request.form())
    tasks = BackgroundTasks()
    tasks.add_task(parse_and_submit_tags, payload=payload)    
    return JSONResponse({'ok': ''}, background=tasks)


@app.route('/series-event', methods=["POST"])
async def post_series_event(request):
    payload    = dict(await request.form())
    sender     = payload.get("sender","Unknown")
    event      = payload.get("event",monitor.s_events.UKNOWN)
    series_uid = payload.get("series_uid","")
    file_count = payload.get("file_count",0)
    target     = payload.get("target","")
    info       = payload.get("info","")

    query = series_events.insert().values(
        sender=sender, event=event, series_uid=series_uid, file_count=file_count, 
        target=target, info=info, time=datetime.datetime.now()
    )
    tasks = BackgroundTasks()
    tasks.add_task(execute_db_operation, operation=query)
    return JSONResponse({'ok': ''}, background=tasks)


###################################################################################
## Main entry function
###################################################################################

if __name__ == '__main__':
    logger.info("")
    logger.info(f"Hermes Bookkeeper ver {hermes_bookkeeper_version}")
    logger.info("----------------------------")
    logger.info("")

    uvicorn.run(app, host=BOOKKEEPER_HOST, port=BOOKKEEPER_PORT)
