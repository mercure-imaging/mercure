"""
database.py
===========
Database functions needed for the bookkeeper service.
"""

# Standard python includes
import sqlalchemy
from sqlalchemy.sql import func
import databases

# Starlette-related includes

# App-specific includes
import common.monitor as monitor
import bookkeeping.config as bk_config


###################################################################################
## Definition of database tables
###################################################################################


database = databases.Database(bk_config.DATABASE_URL)
metadata = sqlalchemy.MetaData(schema=bk_config.DATABASE_SCHEMA)

if 'sqlite://' in bk_config.DATABASE_URL:
    # SQLite does not support JSONB natively, so we use TEXT instead
    JSONB = sqlalchemy.types.Text()
else:
    from sqlalchemy.dialects.postgresql import JSONB
# 
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
    sqlalchemy.Column("client_timestamp", sqlalchemy.Integer),
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
    sqlalchemy.Column("parent_id", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime),
    sqlalchemy.Column("series_uid", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("study_uid", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("data", JSONB),
)

tests_table = sqlalchemy.Table(
    "tests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("type", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rule_type", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("time_begin", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("time_end", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("task_id", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("data", JSONB, nullable=True),
)

processor_logs_table = sqlalchemy.Table(
    "processor_logs",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("task_id", sqlalchemy.String, sqlalchemy.ForeignKey("tasks.id"), nullable=True),
    sqlalchemy.Column("module_name", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("logs", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime, nullable=True),
)

processor_outputs_table = sqlalchemy.Table(
    "processor_outputs",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("time", sqlalchemy.DateTime(timezone=True), server_default=func.now()),
    sqlalchemy.Column("task_id", sqlalchemy.String, sqlalchemy.ForeignKey("tasks.id"),nullable=True),
    sqlalchemy.Column("task_acc", sqlalchemy.String),
    sqlalchemy.Column("task_mrn", sqlalchemy.String),
    sqlalchemy.Column("module", sqlalchemy.String),
    sqlalchemy.Column("index", sqlalchemy.Integer),
    sqlalchemy.Column("settings", JSONB),
    sqlalchemy.Column("output", JSONB),
)
