import inspect
import logging
from pathlib import Path
import sys
import traceback
from typing import Any, Optional
from common import enums, monitor
import daiquiri


class BookkeeperHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        # Grab the first argument as a task_id
        if len(record.args) > 0:
            record.task = record.args[0]
            record.args = record.args[1:]

            if not hasattr(record, "_daiquiri_extra_keys"):
                record._daiquiri_extra_keys = set("task")
            else:
                record._daiquiri_extra_keys.add("task")

        message = record.msg

        if record.levelname == "CRITICAL":
            severity = enums.severity.CRITICAL
        elif record.levelname == "ERROR":
            severity = enums.severity.ERROR
        elif record.levelname == "WARNING":
            severity = enums.severity.WARNING

        if getattr(record, "task", None) is not None:
            if severity in (enums.severity.CRITICAL, enums.severity.ERROR):
                t_type = enums.s_events.ERROR
            else:
                t_type = enums.s_events.UNKNOWN
            monitor.send_task_event(
                t_type,
                record.task,
                getattr(record, "file_count", 0),
                getattr(record, "target", ""),
                message,
            )

        monitor.send_event(getattr(record, "event_type", enums.m_events.PROCESSING), severity, message)

        # syslog.syslog(priority, message)


class ForceModuleFilter(logging.Filter):
    def __init__(self, module, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.module = module

    def filter(self, record) -> bool:
        record.module = self.module
        return True

    def __repr__(self) -> str:
        return f"<ForceModuleFilter module={self.module}>"


filter = ForceModuleFilter(module="unknown")


def severity_to_loglevel(level: enums.severity) -> int:
    map = {
        enums.severity.CRITICAL: logging.CRITICAL,
        enums.severity.ERROR: logging.ERROR,
        enums.severity.WARNING: logging.WARNING,
        enums.severity.INFO: logging.INFO,
    }
    return map.get(level, logging.INFO)


def handle_error(
    msg: str,
    task_id: Optional[str] = None,
    *,
    file_count: int = 0,
    target: str = "",
    exc_info: Optional[Any] = None,
    event_type: enums.m_events = enums.m_events.PROCESSING,
    severity: enums.severity = enums.severity.ERROR,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Logs an error message and sends an event to the monitoring system
    """

    # Allow overriding of the exception info
    log_msg = msg

    if logger is None:
        logger = daiquiri.getLogger("handle_error")
        module = "exceptions"
        try:
            if exc_info[2] is not None:
                exc_traceback = exc_info[2]
                module = Path(exc_traceback.tb_frame.f_code.co_filename).stem
            else:
                module = Path(inspect.stack()[1][1]).stem
        except:
            pass

    logger.logger.removeFilter(filter)
    filter.module = module
    logger.logger.addFilter(filter)

    if task_id:
        extra = {"task": task_id}
    else:
        extra = {}

    if target:
        extra["target"] = target
    if file_count:
        extra["file_count"] = file_count

    extra["event_type"] = event_type
    # Log depending on severity

    logger.log(severity_to_loglevel(severity), log_msg, exc_info=exc_info, extra=extra)
