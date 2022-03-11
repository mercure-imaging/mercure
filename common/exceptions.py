import logging
import sys
import traceback
from common import monitor


def handle_error(
    msg: str,
    logger: logging.Logger,
    task_id=None,
    file_count=0,
    target="",
    exc_info=None,
    event_type=monitor.m_events.PROCESSING,
    severity=monitor.severity.ERROR,
) -> None:
    """
    Logs an error message and sends an event to the monitoring system
    """
    if task_id is not None:
        log_msg = msg + " { task " + task_id + " }"
    else:
        log_msg = msg
    if severity == monitor.severity.CRITICAL:
        logger.critical(log_msg)
    elif severity == monitor.severity.ERROR:
        logger.error(log_msg)
    elif severity == monitor.severity.WARNING:
        logger.warning(log_msg)
    elif severity == monitor.severity.INFO:
        logger.info(log_msg)
    else:
        logger.info(log_msg)

    if exc_info is None:
        exc_info = sys.exc_info()
    if exc_info[0] is not None:
        logger.error("".join(traceback.format_exception(*exc_info)))

    if task_id is not None:
        if severity in (monitor.severity.CRITICAL, monitor.severity.ERROR):
            t_type = monitor.s_events.ERROR
        else:
            t_type = monitor.s_events.UNKNOWN
        monitor.send_task_event(t_type, task_id, file_count, target, msg)
    monitor.send_event(event_type, severity, msg)


class MercureException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message
        self.exc_info = sys.exc_info()

    def task_event(self, logger, task_id, file_count=0, target=""):
        logger.error(self.message)
        if self.exc_info[0] is not None:
            logger.error("".join(traceback.format_exception(*self.exc_info)))
        monitor.send_task_event(monitor.s_events.ERROR, task_id, file_count, target, self.message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, self.message)
