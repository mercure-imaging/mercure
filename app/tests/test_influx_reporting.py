"""
test_influx_reporting.py
========================

Metrics reporting to InfluxDB: one long-lived client per process, batching left to the library, and a
close that is bounded. Recording doubles stand in for the client and writer, so delivery itself is not
verified here.
"""
import asyncio
import logging
import time
from typing import Any, List, Optional

import pytest
import common.helper as helper
import common.influxdb as influxdb


class RecordingWriteApi:
    def __init__(self, options: Any = None) -> None:
        self.options = options
        self.records: List[Any] = []
        self.closed = False

    def write(self, bucket: str = "", record: Any = None, **kwargs) -> None:
        self.records.append(record)

    def close(self) -> None:
        self.closed = True


class RecordingClient:
    """Stands in for ``InfluxDBClient``: counts how many are built and what they are asked to do."""

    def __init__(self, *args, **kwargs) -> None:
        RecordingClient.instances.append(self)
        self.kwargs = kwargs
        self.write_apis: List[RecordingWriteApi] = []
        self.closed = False

    def write_api(self, write_options: Any = None) -> RecordingWriteApi:
        api = RecordingWriteApi(write_options)
        self.write_apis.append(api)
        return api

    def close(self) -> None:
        self.closed = True


RecordingClient.instances = []


@pytest.fixture
def clients(monkeypatch):
    RecordingClient.instances = []
    monkeypatch.setattr(influxdb, "InfluxDBClient", RecordingClient)
    return RecordingClient


# ---------------------------------------------------------------------------------------------


def test_one_client_per_sender_not_one_per_metric(clients):
    """Metrics share a client; they do not build one apiece.

    Fifty metrics used to mean fifty clients, each with its own async write machinery, constructed on
    the service's event loop thread.
    """
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.router.instance")

    for index in range(50):
        sender.send("events.run", index)

    assert len(clients.instances) == 1, (
        f"{len(clients.instances)} InfluxDB clients for 50 metrics: the metrics path rebuilds the "
        f"client and its writer on every call"
    )
    assert len(sender.write_api.records) == 50


def test_the_library_does_the_batching(clients):
    """Batching comes from ``WriteOptions``, not from a queue of our own."""
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.router.instance")
    options = sender.write_api.options

    assert options is not None, "no WriteOptions: every point is written on its own"
    assert getattr(options, "batch_size", 0) > 1, "batching is not configured"
    assert getattr(options, "flush_interval", 0) > 0, "no flush interval: buffered points never leave"
    assert getattr(options, "max_close_wait", 0) <= 2_000, "closing the writer can block shutdown for long"


def test_close_flushes_and_releases(clients):
    """Shutdown hands the buffered points over and closes the client."""
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.test")
    sender.send("events.boot", 1)

    sender.close()

    assert sender.write_api.closed, "the write API was left open, so buffered points are lost"
    assert clients.instances[0].closed, "the client was left open"
    sender.close()  # idempotent: called from a shutdown path that may run more than once


def test_a_broken_influx_does_not_break_the_service(clients, monkeypatch):
    """Metric reporting must never be the reason a study fails to route."""
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.test")

    def explode(bucket: str = "", record: Any = None, **kwargs):
        raise OSError("influx is down")

    monkeypatch.setattr(sender.write_api, "write", explode)
    sender.send("events.run", 1)  # must not raise


def test_a_failing_flush_is_said_out_loud(clients, caplog):
    """close() is a best-effort flush: it cannot verify delivery, but it must not fail quietly.

    The writer being closed without complaint used to mean nothing about the points that were meant to
    go through it.
    """
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.test")

    def explode() -> None:
        raise OSError("influx is down")

    sender.write_api.close = explode  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR):
        sender.close()

    assert any("buffered metrics are lost" in r.getMessage() for r in caplog.records), (
        "a flush that failed was swallowed, so the contract read as though the points had arrived"
    )
    assert clients.instances[0].closed, "one step failing must not leave the client open"
    assert sender.closed


def test_points_are_stamped_when_sent_not_when_written(clients):
    """Batching and retries delay the write; the point must carry the time it was measured."""
    sender = influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.test")
    sender.send("events.run", 1, timestamp=1_700_000_000.5)
    assert sender.write_api.records[0].to_line_protocol().endswith(" 1700000000500000000")


def test_an_in_flight_write_is_bounded(clients):
    """The library's writer thread is not a daemon, so an unbounded write would hold the process at exit."""
    influxdb.Sender("http://influx:8086", "token", "org", "bucket", "mercure.test")
    timeout = clients.instances[0].kwargs.get("timeout")
    assert timeout is not None and timeout <= 10_000, "no request timeout: a hung write holds the exit"
    worst_case_ms = timeout + influxdb.MAX_RETRY_TIME_MS
    assert worst_case_ms <= 20_000, f"an in-flight write can outlast the shutdown budget ({worst_case_ms} ms)"


def test_the_default_sender_is_closed_at_shutdown(clients, monkeypatch):
    """The shared client has to be released by the same drain that stops the services."""
    influxdb.init("http://influx:8086", "token", "org", "bucket", "mercure.dispatcher.instance")
    sender = influxdb.default_sender
    assert sender is not None
    sender.send("events.run", 1)

    loop = helper.asyncio.new_event_loop()
    try:
        helper.drain_pending_tasks(loop, monitor_timeout=0.5, task_timeout=0.5)
    finally:
        loop.close()
        influxdb.default_sender = None

    assert sender.write_api.closed, "shutdown left the metrics client open: buffered metrics are lost"
