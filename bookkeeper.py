#!/usr/bin/python

# Standard python includes
import uvicorn
import os
import asyncio
import datetime
import logging

# 3rd party
import daiquiri
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse
from starlette.responses import JSONResponse
from starlette.responses import RedirectResponse
from starlette.config import Config
from starlette.datastructures import URL, Secret
import databases
import sqlalchemy
 
# App-specific includes

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

hermes_events = sqlalchemy.Table(
    "hermes_events",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("sender", sqlalchemy.String, default="Unknown"),
    sqlalchemy.Column("event", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("severity", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("description", sqlalchemy.String, default="")
)

dicom_file = sqlalchemy.Table(
    "dicom_file",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("filename", sqlalchemy.String),
    sqlalchemy.Column("file_uid", sqlalchemy.String),
    sqlalchemy.Column("series_uid", sqlalchemy.String)
)

dicom_series = sqlalchemy.Table(
    "dicom_series",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("series_uid", sqlalchemy.String),
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

dicom_series_map = sqlalchemy.Table(
    "dicom_series_map",
    metadata,
    sqlalchemy.Column("file_id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("series_id", sqlalchemy.Integer)
)

file_event = sqlalchemy.Table(
    "file_event",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("dicom_file", sqlalchemy.Integer),
    sqlalchemy.Column("event", sqlalchemy.Integer)
)

series_event = sqlalchemy.Table(
    "series_event",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("dicom_series", sqlalchemy.Integer),
    sqlalchemy.Column("event", sqlalchemy.Integer),
    sqlalchemy.Column("source", sqlalchemy.String),
    sqlalchemy.Column("target", sqlalchemy.String),
    sqlalchemy.Column("file_count", sqlalchemy.Integer)
)


def create_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.create_all(engine)


###################################################################################
## Endpoints
###################################################################################

@app.on_event("startup")
async def startup():
    await database.connect()
    create_database()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.route('/test')
async def test_endpoint(request):
    return JSONResponse({'running': 'true'})


@app.route('/hermes-event', methods=["POST"])
@database.transaction()
async def post_hermes_event(request):
    sender=request.query_params.get("sender","Unknown")
    event=int(request.query_params.get("event",0))
    severity=int(request.query_params.get("severity",0))    
    description=request.query_params.get("description","")       

    query = hermes_events.insert().values(
        sender=sender, event=event, severity=severity, description=description, time=datetime.datetime.now()
    )
    await database.execute(query)
    return JSONResponse({'success': 'true'})


###################################################################################
## Main entry function
###################################################################################

if __name__ == '__main__':
    logger.info("")
    logger.info(f"Hermes Bookkeeper ver {hermes_bookkeeper_version}")
    logger.info("----------------------------")
    logger.info("")

    uvicorn.run(app, host=BOOKKEEPER_HOST, port=BOOKKEEPER_PORT)
