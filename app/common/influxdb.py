"""
Send data to InfluxDB metrics server.
"""

import logging
import time
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import ASYNCHRONOUS
from typing import Optional, Union

__all__ = ['Sender', 'init', 'send']


default_sender = None
logger = logging.getLogger(__name__)


def _has_whitespace(value: str) -> bool:
    return not value or value.split(None, 1)[0] != value


class Sender:
    def __init__(self, host: str, token: str, org: str, bucket: str, prefix: str,
                 log_sends: bool = False, raise_send_errors: bool = False):
        """Initialize a Sender instance
        """
        self.host = host
        self.token = token
        self.org = org
        self.bucket = bucket
        self.prefix = prefix
        self.log_sends = log_sends
        self.raise_send_errors = raise_send_errors
        self.type = ASYNCHRONOUS

    def build_message(self, metric: str, value: Union[int, float], timestamp: Optional[float]) -> Point:
        """Build an InfluxDB message to send and return it."""
        if _has_whitespace(metric):
            raise ValueError('"metric" must not have whitespace in it')
        if not isinstance(value, (int, float)):
            raise TypeError('"value" must be an int or a float, not a {}'.format(
                type(value).__name__))

        message = Point(self.prefix + "." + metric).field("value", value)

        return message

    def send(self, metric: str, value: Union[int, float], timestamp: Optional[float] = None):
        """Send given metric and (int or float) value to InfluxDB host.
        """
        if timestamp is None:
            timestamp = time.time()
        message = self.build_message(metric, value, timestamp)

        self.send_socket(message)

    def send_message(self, message: Point):
        sender = InfluxDBClient(url=self.host, token=self.token, org=self.org, bucket=self.bucket)
        write_api = sender.write_api(write_options=self.type)
        write_api.write(bucket=self.bucket, record=message)

    def send_socket(self, message: Point):
        """
        """
        if self.log_sends:
            start_time = time.time()
        try:
            self.send_message(message)
        except Exception as error:
            if self.raise_send_errors:
                raise
            logger.error('error sending message {!r}: {}'.format(message, error))
        else:
            if self.log_sends:
                elapsed_time = time.time() - start_time
                logger.info('sent message {!r} to ({}, {}, {}, {}, {}) in {:.03f} seconds'.format(
                    message.to_line_protocol(), self.host, self.token, self.org, self.bucket, self.type, elapsed_time))


def init(*args, **kwargs) -> None:
    """Initialize default Sender instance with given args."""
    global default_sender
    default_sender = Sender(*args, **kwargs)


def send(*args, **kwargs):
    """Send message using default Sender instance."""
    global default_sender
    if default_sender is None:
        logger.error('default Sender instance not initialized')
        return
    default_sender.send(*args, **kwargs)
