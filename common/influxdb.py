"""Send data to Graphite metrics server (synchronously or on a background thread).

For example usage, see README.rst.

This code is licensed under a permissive MIT license -- see LICENSE.txt.

The graphyte project lives on GitHub here:
https://github.com/benhoyt/graphyte
"""

import atexit
import logging
try:
    import queue
except ImportError:
    import Queue as queue  # Python 2.x compatibility
import threading
import time
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, ASYNCHRONOUS

__all__ = ['Sender', 'init', 'send']

__version__ = '1.7.1'

default_sender = None
logger = logging.getLogger(__name__)


def _has_whitespace(value):
    return not value or value.split(None, 1)[0] != value


class Sender:
    def __init__(self, host, token, org, bucket, prefix, timeout=5, interval=None,
                 queue_size=None, log_sends=False, batch_size=1000, tags={},
                 raise_send_errors=False):
        """Initialize a Sender instance, starting the background thread to
        send messages at given interval (in seconds) if "interval" is not
        None. Send at most "batch_size" messages per socket send operation.
        """

        self.host = host
        self.token = token
        self.org = org
        self.bucket = bucket
        self.prefix = prefix
        self.timeout = timeout
        self.interval = interval
        self.log_sends = log_sends
        self.batch_size = batch_size
        self.tags = tags
        self.raise_send_errors = raise_send_errors
        self.type = ASYNCHRONOUS

        if self.interval is not None:
            if raise_send_errors:
                raise ValueError('raise_send_errors must be disabled when interval is set')
            if queue_size is None:
                queue_size = int(round(interval)) * 100
            self._queue = queue.Queue(maxsize=queue_size)
            self._thread = threading.Thread(target=self._thread_loop)
            self._thread.daemon = True
            self._thread.start()
            atexit.register(self.stop)

    def __del__(self):
        self.stop()

    def stop(self):
        """Tell the sender thread to finish and wait for it to stop sending
        (should be at most "timeout" seconds).
        """
        if self.interval is not None:
            self._queue.put_nowait(None)
            self._thread.join()
            self.interval = None

    def build_message(self, metric, value, timestamp):
        """Build an InfluxDB message to send and return it."""
        if _has_whitespace(metric):
            raise ValueError('"metric" must not have whitespace in it')
        if not isinstance(value, (int, float)):
            raise TypeError('"value" must be an int or a float, not a {}'.format(
                type(value).__name__))

        message = Point(self.prefix + "." + metric).field("value", value)

        return message

    def send(self, metric, value, timestamp=None):
        """Send given metric and (int or float) value to InfluxDB host.
        Performs send on background thread if "interval" was specified when
        creating this Sender.

        If a "tags" dict is specified, send the tags to the InfluxDB host along
        with the metric
        """
        if timestamp is None:
            timestamp = time.time()
        message = self.build_message(metric, value, timestamp)

        if self.interval is None:
            self.send_socket(message)
        else:
            try:
                self._queue.put_nowait(message)
            except queue.Full:
                logger.error('queue full when sending {!r}'.format(message))

    def send_message(self, message):
        sender = InfluxDBClient(url=self.host, token=self.token, org=self.org, bucket=self.bucket)
        write_api = sender.write_api(write_options=self.type)
        write_api.write(bucket=self.bucket, record=message)

    def send_socket(self, message):
        """Low-level function to send message to this Sender.
        You should usually call send() instead of this function (unless you're
        subclassing or writing unit tests).
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

    def _thread_loop(self):
        """Background thread used when Sender is in asynchronous/interval mode."""
        last_check_time = time.time()
        messages = []
        while True:
            # Get first message from queue, blocking until the next time we
            # should be sending
            time_since_last_check = time.time() - last_check_time
            time_till_next_check = max(0, self.interval - time_since_last_check)
            try:
                message = self._queue.get(timeout=time_till_next_check)
            except queue.Empty:
                pass
            else:
                if message is None:
                    # None is the signal to stop this background thread
                    break
                messages.append(message)

                # Get any other messages currently on queue without blocking,
                # paying attention to None ("stop thread" signal)
                should_stop = False
                while True:
                    try:
                        message = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if message is None:
                        should_stop = True
                        break
                    messages.append(message)
                if should_stop:
                    break

            # If it's time to send, send what we've collected
            current_time = time.time()
            if current_time - last_check_time >= self.interval:
                last_check_time = current_time
                for i in range(0, len(messages), self.batch_size):
                   batch = messages[i:i + self.batch_size]
                   self.send_socket(b''.join(batch))
                messages = []

        # Send any final messages before exiting thread
        for i in range(0, len(messages), self.batch_size):
            batch = messages[i:i + self.batch_size]
            self.send_socket(b''.join(batch))

def init(*args, **kwargs):
    """Initialize default Sender instance with given args."""
    global default_sender
    default_sender = Sender(*args, **kwargs)


def send(*args, **kwargs):
    """Send message using default Sender instance."""
    default_sender.send(*args, **kwargs)