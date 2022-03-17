import logging, re, sys, os
import daiquiri
from typing import Optional
from common import exceptions, helper

setup_complete = False


class ExceptionsKeywordArgumentAdapter(daiquiri.KeywordArgumentAdapter):
    def process(self, msg, kwargs):
        msg, kwargs = super().process(msg, kwargs)
        # if kwargs.get("exc_info") not in (False, None):
        #     kwargs["exc_info"] = True if sys.exc_info()[2] is not None else False
        return msg, kwargs


def get_logger(name: Optional[str] = "handle_error", is_monitor=False) -> daiquiri.KeywordArgumentAdapter:
    global setup_complete

    if not setup_complete:
        daiquiri.setup(
            get_loglevel(),
            outputs=(
                daiquiri.output.Stream(
                    formatter=daiquiri.formatter.ColorExtrasFormatter(
                        fmt=get_logformat(), keywords=["event_type", "severity"]
                    )
                ),
            ),
        )

        if not is_monitor:
            setup_complete = True
            logger = ExceptionsKeywordArgumentAdapter(logging.getLogger(name), {})

            handler = exceptions.BookkeeperHandler()
            logger.logger.addHandler(handler)
            return logger

    if not is_monitor:
        return ExceptionsKeywordArgumentAdapter(logging.getLogger(name), {})
    return logging.getLogger(name)


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
        return "%(asctime)s %(color)s%(levelname)-8.8s " "%(module)s: %(message)s%(color_stop)s"
