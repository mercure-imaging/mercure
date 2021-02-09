class mercure_defs:
    VERSION = "0.2a"
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
    LAST_RECEIVE_TIME = "last_receive_time"
    CREATION_TIME = "creation_time"
    STUDY_UID = "study_uid"
    COMPLETE_TRIGGER = "complete_trigger"
    COMPLETE_REQUIRED_SERIES = "complete_required_series"
    RECEIVED_SERIES = "received_series"


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


class mercure_events:
    RECEPTION = 0
    COMPLETION = 1
    ERROR = 2
