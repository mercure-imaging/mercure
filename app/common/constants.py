"""
constants.py
============
mercure-wide constants, used for standardizing key names and extensions.
"""

# App-specific includes
from enum import IntEnum

from common.version import mercure_version


class mercure_defs:
    VERSION = mercure_version.get_version_string()
    SEPARATOR = "#"


class mercure_names:
    LOCK = ".lock"
    PROCESSING = ".processing"
    RUNNING = ".running"
    ERROR = ".error"
    TAGS = ".tags"
    HALT = "HALT"
    TASKFILE = "task.json"
    SENDLOG = "sent.txt"
    DCM = ".dcm"
    DCMFILTER = "*.dcm"
    FORCE_COMPLETE = ".force-complete"


class mercure_sections:
    INFO = "info"
    DISPATCH = "dispatch"
    PROCESS = "process"
    JOURNAL = "journal"
    NOTIFICATION = "notification"
    FILES = "files"
    STUDY = "study"


class mercure_config:
    RULES = "rules"
    TARGETS = "targets"
    MODULES = "modules"


class mercure_folders:
    INCOMING = "incoming_folder"
    STUDIES = "studies_folder"
    OUTGOING = "outgoing_folder"
    SUCCESS = "success_folder"
    ERROR = "error_folder"
    DISCARD = "discard_folder"
    PROCESSING = "processing_folder"


class mercure_actions:
    ROUTE = "route"
    BOTH = "both"
    PROCESS = "process"
    DISCARD = "discard"
    NOTIFICATION = "notification"


class mercure_rule:
    RULE = "rule"
    ACTION = "action"
    ACTION_TRIGGER = "action_trigger"
    STUDY_TRIGGER_CONDITION = "study_trigger_condition"
    STUDY_TRIGGER_CONDITION_TIMEOUT = "timeout"
    STUDY_TRIGGER_CONDITION_RECEIVED_SERIES = "received_series"
    STUDY_TRIGGER = "study_trigger"
    PRIORITY = "priority"
    DISABLED = "disabled"
    FALLBACK = "fallback"
    PROCESSING_MODULE = "processing_module"
    TARGET = "target"
    NOTIFICATION_WEBHOOK = "notification_webhook"
    NOTIFICATION_PAYLOAD = "notification_payload"
    NOTIFICATION_TRIGGER_RECEPTION = "notification_trigger_reception"
    NOTIFICATION_TRIGGER_COMPLETION = "notification_trigger_completion"
    NOTIFICATION_TRIGGER_ERROR = "notification_trigger_error"
    PROCESSING_MODULE = "processing_module"


class mercure_study:
    STUDY_UID = "study_uid"
    CREATION_TIME = "creation_time"
    LAST_RECEIVE_TIME = "last_receive_time"
    RECEIVED_SERIES = "received_series"
    COMPLETE_TRIGGER = "complete_trigger"
    COMPLETE_REQUIRED_SERIES = "complete_required_series"
    COMPLETE_FORCE = "complete_force"


class mercure_info:
    ACTION = "action"
    UID = "uid"
    UID_TYPE = "uid_type"
    TRIGGERED_RULES = "triggered_rules"
    MRN = "mrn"
    ACC = "acc"
    MERCURE_VERSION = "mercure_version"
    MERCURE_APPLIANCE = "mercure_appliance"
    MERCURE_SERVER = "mercure_server"


class mercure_options:
    TRUE = "True"
    FALSE = "False"
    SERIES = "series"
    STUDY = "study"
    NORMAL = "normal"
    URGENT = "urgent"
    OFFPEAK = "offpeak"
    MISSING = "MISSING"
    INVALID = "#@INVALID@#"


class mercure_events(IntEnum):
    RECEIVED = 0
    COMPLETED = 1
    ERROR = 2
