import logging, re, sys, os
from typing import Tuple
import daiquiri
from common import helper
from common import enums, monitor

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
            severity = enums.severity.CRITICAL
        elif record.levelname == "ERROR":
            severity = enums.severity.ERROR
        elif record.levelname == "WARNING":
            severity = enums.severity.WARNING

        task_id = getattr(record, "task", None)
        if task_id is not None:
            if severity in (enums.severity.CRITICAL, enums.severity.ERROR):
                t_type = enums.task_event.ERROR
            else:
                t_type = enums.task_event.UNKNOWN
            monitor.send_task_event(
                t_type,
                task_id,  # type: ignore
                getattr(record, "file_count", 0),
                getattr(record, "target", ""),
                message,
            )

        monitor.send_event(getattr(record, "event_type", enums.m_events.PROCESSING), severity, message)


# This breaks uvicorn
# class CustomLogRecord(logging.LogRecord):
#     def getMessage(self):
#         msg = str(self.msg)
#         if self.args:
#             msg = msg % self.args

#         context_task = getattr(self, "context_task", None)
#         task = self.args_task if self.args_task is not None else context_task
#         if task is not None:
#             msg = f"{msg} [task: {task}]"
#         return msg

#     def __init__(self, name, level, pathname, lineno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
#         if len(args) > 0:
#             self.args_task = args[0]
#             args = args[1:]
#         else:
#             self.args_task = None
#         super().__init__(name, level, pathname, lineno, msg, None, exc_info, func, sinfo, **kwargs)


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
