import logging, re, sys, os
from typing import Tuple
import daiquiri
from common import helper
from common import event_types, monitor

setup_complete = False


class BookkeeperHandler(logging.Handler):
    def __init__(self, level=logging.WARNING) -> None:
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        task = None
        if isinstance(record.args, (list, tuple)) and len(record.args) > 0:
            task = record.args[0]
            record.args = record.args[1:]

            if task is not None:
                record.task = task  # type: ignore

                if not hasattr(record, "_daiquiri_extra_keys"):
                    record._daiquiri_extra_keys = set("task")  # type: ignore
                else:
                    record._daiquiri_extra_keys.add("task")  # type: ignore

        message = record.msg

        if record.levelname == "CRITICAL":
            severity = event_types.severity.CRITICAL
        elif record.levelname == "ERROR":
            severity = event_types.severity.ERROR
        elif record.levelname == "WARNING":
            severity = event_types.severity.WARNING

        task_id = getattr(record, "task", None)
        if task_id is not None:
            if severity in (event_types.severity.CRITICAL, event_types.severity.ERROR):
                t_type = event_types.task_event.ERROR
            else:
                t_type = event_types.task_event.UNKNOWN
            monitor.send_task_event(
                t_type,
                task_id,  # type: ignore
                getattr(record, "file_count", 0),
                getattr(record, "target", ""),
                message,
            )

        monitor.send_event(getattr(record, "event_type", event_types.m_events.PROCESSING), severity, message)


class ExceptionsKeywordArgumentAdapter(daiquiri.KeywordArgumentAdapter):
    def __init__(self, logger: logging.Logger, extra: dict) -> None:
        super().__init__(logger, extra)
        self.logger.addHandler(BookkeeperHandler())

    def process(self, msg, kwargs) -> Tuple[str, dict]:
        if sys.exc_info()[0] is not None and "exc_info" not in kwargs:
            kwargs["exc_info"] = True
        msg, kwargs = super().process(msg, kwargs)

        extra = kwargs["extra"]
        if "context_task" in extra:
            extra["task"] = extra["context_task"]
            del extra["context_task"]
            extra["_daiquiri_extra_keys"].discard("context_task")
            extra["_daiquiri_extra_keys"].add("task")

        return msg, kwargs  # {"extra": {"_daiquiri_extra_keys": set()}}

    def setTask(self, task_id: str) -> None:
        self.extra["context_task"] = task_id
        logger.debug(f"Setting task")

    def clearTask(self) -> None:
        if "context_task" in self.extra:
            logger.debug("Clearing task")
            del self.extra["context_task"]


def clear_task_decorator(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            get_logger().clearTask()

    return wrapper


def clear_task_decorator_async(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        finally:
            get_logger().clearTask()

    return wrapper


# logging.setLogRecordFactory(CustomLogRecord)

logger = ExceptionsKeywordArgumentAdapter(logging.getLogger("handle_error"), {})


def get_logger() -> ExceptionsKeywordArgumentAdapter:
    global setup_complete
    global logger
    if not setup_complete:
        daiquiri.setup(
            get_loglevel(),
            outputs=(
                daiquiri.output.Stream(
                    formatter=daiquiri.formatter.ColorExtrasFormatter(
                        fmt=get_logformat(), keywords=["event_type", "severity", "context_task"]
                    )
                ),
            ),
        )
        setup_complete = True
        return logger

    return logger


def get_loglevel() -> int:
    """Returns the logging level that should be used for printing messages."""
    if any(re.findall(r"pytest|py.test", sys.argv[0])):
        return logging.DEBUG

    level = os.getenv("MERCURE_LOG_LEVEL", "info").lower()
    if level == "error":
        return logging.ERROR
    if level == "info":
        return logging.INFO
    if level == "debug":
        return logging.DEBUG
    return logging.INFO


def get_logformat() -> str:
    """Returns the format that should be used for log messages. Includes the time for docker and nomad, but not for systemd as journalctl
    already outputs the time of the log events."""
    runner = helper.get_runner()
    if runner == "systemd":
        return "%(color)s%(levelname)-8.8s " "%(module)s: %(message)s%(color_stop)s %(extras)s"
    else:
        return "%(asctime)s %(color)s%(levelname)-8.8s " "%(module)s: %(message)s%(color_stop)s %(extras)s"
