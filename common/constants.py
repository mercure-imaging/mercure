
class mercure_names:
    LOCK       = ".lock"
    PROCESSING = ".processing"
    ERROR      = ".error"
    TAGS       = ".tags"
    HALT       = "HALT"
    TASKFILE   = "task.json"
    SENDLOG    = "sent.txt"
    DCM        = ".dcm"
    DCMFILTER  = "*.dcm"

class mercure_sections:
    INFO       = "info"
    DISPATCH   = "dispatch"
    PROCESS    = "process"
    JOURNAL    = "journal"

class mercure_actions:
    ROUTE        = "route"
    BOTH         = "both"
    PROCESS      = "process"
    DISCARD      = "discard"
    NOTIFICATION = "notification"
