import inspect
import logging
from pathlib import Path
import sys
import traceback
from typing import Any, Optional
from common import enums, monitor


class BookkeeperHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)

        if record.levelname == "CRITICAL":
            severity = enums.severity.CRITICAL
        elif record.levelname == "ERROR":
            severity = enums.severity.ERROR
        elif record.levelname == "WARNING":
            severity = enums.severity.WARNING

        if hasattr(record, "task"):
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
    if exc_info is None:
        exc_info = sys.exc_info()

    if task_id is not None:
        log_msg = msg + " { task " + task_id + " }"
    else:
        log_msg = msg

    if logger is None:
        logger = logging.getLogger("exceptions")
        module = "exceptions"
        try:
            if exc_info[2] is not None:
                exc_traceback = exc_info[2]
                module = Path(exc_traceback.tb_frame.f_code.co_filename).stem
            else:
                module = Path(inspect.stack()[1][1]).stem
        except:
            pass

    logger.removeFilter(filter)
    filter.module = module
    logger.addFilter(filter)

    # Log depending on severity
    if severity == enums.severity.CRITICAL:
        logger.critical(log_msg)
    elif severity == enums.severity.ERROR:
        logger.error(log_msg)
    elif severity == enums.severity.WARNING:
        logger.warning(log_msg)
    elif severity == enums.severity.INFO:
        logger.info(log_msg)
    else:
        logger.info(log_msg)

    if exc_info[0] is not None:
        logger.error("".join(traceback.format_exception(*exc_info)))

    # if we have a task_id, send a task event
    if task_id is not None:
        #
        if severity in (enums.severity.CRITICAL, enums.severity.ERROR):
            t_type = enums.s_events.ERROR
        else:
            t_type = enums.s_events.UNKNOWN
        monitor.send_task_event(t_type, task_id, file_count, target, msg)
    monitor.send_event(event_type, severity, msg)
