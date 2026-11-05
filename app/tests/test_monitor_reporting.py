"""
test_monitor_reporting.py
=========================

Contract for the reporting path to the bookkeeper: a bounded queue with one consumer, shared pools,
logged drops, and a shutdown drain with a deadline. Delivery is serial within one process only.
"""
import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple, Union

import aiohttp
import pytest
import pytest_asyncio
from common.constants import mercure_names
import common.helper as helper
import common.monitor as monitor
from docker.models.containers import ContainerCollection
from docker.models.images import ImageCollection
from process import processor

from .test_processor import config_partial, create_and_route
from .testing_common import FakeDockerContainer, FakeImageContainer, make_fake_processor


class StubBookkeeper:
    """Stand-in for the bookkeeper transport: latency, refusals, failures and hangs on demand."""

    def __init__(self) -> None:
        self.sent: List[Tuple[str, Dict[str, Any]]] = []
        #: Wall-clock time each task_id was handed over, for "stamped before it was sent" assertions.
        self.delivered_at: Dict[str, float] = {}
        #: Seconds per endpoint, or a callable taking the request kwargs.
        self.delays: Dict[str, Union[float, Callable[[Dict[str, Any]], float]]] = {}
        self.hang_for: List[str] = []
        self.reject_for: List[str] = []
        self.raise_for: List[str] = []
        self.blocked = False

    async def __call__(self, endpoint: str, kwargs: Dict[str, Any], *args, **kw) -> bool:
        # Interruptible, so an outage can be repaired part-way through a test.
        while self.blocked or endpoint in self.hang_for:
            await asyncio.sleep(0.01)
        delay = self.delays.get(endpoint, 0.0)
        delay = delay(kwargs) if callable(delay) else delay
        if delay:
            await asyncio.sleep(delay)
        if endpoint in self.raise_for:
            raise TypeError(f"poison event: {endpoint}")
        if endpoint in self.reject_for:
            return False
        self.sent.append((endpoint, kwargs))
        self.delivered_at[kwargs.get("data", {}).get("task_id", endpoint)] = time.time()
        return True

    def endpoints(self) -> List[str]:
        return [endpoint for endpoint, _ in self.sent]

    def payload(self, task_id: str) -> Dict[str, Any]:
        for _, kwargs in self.sent:
            if kwargs.get("data", {}).get("task_id") == task_id:
                return kwargs["data"]
        raise AssertionError(f"{task_id} was never delivered")


@pytest.fixture
def bookkeeper(mocker, monkeypatch) -> StubBookkeeper:
    """A fresh pipeline, a configured bookkeeper, and a controllable transport."""
    monkeypatch.setattr(monitor, "_pipeline", None)
    monkeypatch.setattr(monitor, "api_key", "test-key")
    monkeypatch.setattr(monitor, "bookkeeper_address", "http://bookkeeper:8080")
    stub = StubBookkeeper()
    mocker.patch.object(monitor, "do_post", new=stub)
    return stub


@pytest_asyncio.fixture
async def reporting(bookkeeper):
    """As above, shut down on the loop that owns the pipeline."""
    try:
        yield bookkeeper
    finally:
        await monitor.shutdown(1.0)


@pytest.fixture
def service_loop(bookkeeper, monkeypatch):
    """A loop of one's own, as ``configure()`` would have captured it. Closed after the case."""
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(monitor, "loop", loop)
    try:
        yield loop
    finally:
        loop.close()


def submit_events(total: int) -> None:
    for index in range(total):
        monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, f"task-{index}", 1, "", "x")


async def wait_until_delivered(timeout: float = 3.0) -> None:
    """Wait for the reporting queue to empty."""
    await asyncio.wait_for(monitor._pipeline.queue.join(), timeout)


def log_messages(caplog) -> List[str]:
    return [r.getMessage() for r in caplog.records]


# ---------------------------------------------------------------------------------------------
# The data path must never wait for the bookkeeper
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processing_does_not_wait_for_the_bookkeeper(fs, mercure_config, mocked, reporting):
    """A bookkeeper that never answers must not stop a task from completing."""
    config = mercure_config({"process_runner": "docker", **config_partial})
    create_and_route(fs, mocked, str(uuid.uuid1()), config)
    fake_run = mocked.Mock(return_value=FakeDockerContainer(),
                           side_effect=make_fake_processor(fs, mocked, False))
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    mocked.patch.object(ImageCollection, "pull", new=mocked.Mock(return_value=FakeImageContainer()))

    reporting.hang_for.append("task-event")
    try:
        await asyncio.wait_for(processor.run_processor(), timeout=10)
    except asyncio.TimeoutError:
        pytest.fail("the processor waited for a bookkeeper report, holding the .processing claim")
    assert list(Path(config.success_folder).rglob(mercure_names.TASKFILE)), "the task did not complete"
    assert not [p for p in Path("/var/processing").iterdir() if p.is_dir()], "the task was left behind"


@pytest.mark.asyncio
async def test_submitting_events_never_blocks_on_a_hung_bookkeeper(reporting):
    """``post()`` is a queue hand-off, not a request, whatever the bookkeeper is doing."""
    reporting.hang_for.append("task-event")
    started = time.monotonic()
    submit_events(50)
    assert time.monotonic() - started < 1.0


@pytest.mark.asyncio
async def test_reporting_is_a_no_op_without_a_bookkeeper(bookkeeper, monkeypatch):
    """An unconfigured bookkeeper creates no pipeline at all."""
    monkeypatch.setattr(monitor, "api_key", None)
    submit_events(100)
    assert monitor._pipeline is None


# ---------------------------------------------------------------------------------------------
# Backlog: bounded by configuration, logged without flooding, recoverable
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_bounded_backlog_drops_overflow_and_recovers(mercure_config, reporting, caplog):
    """A dead bookkeeper costs a bounded backlog and a few log lines; delivery resumes afterwards."""
    mercure_config({"bookkeeper_timeout": 3.0, "bookkeeper_queue_size": 5})
    reporting.blocked = True  # nothing may drain while the bound is being exercised

    with caplog.at_level(logging.ERROR):
        submit_events(40)

    assert monitor._pipeline.queue.maxsize == 5, "the configured backlog size was ignored"
    assert monitor._pipeline.queue.full(), "the bound was not enforced"
    logged = [m for m in log_messages(caplog) if "backlog is full" in m]
    assert logged, "dropping events without saying so is how an outage goes unnoticed"
    assert len(logged) < 10, "one log line per drop would swamp the service log"
    assert monitor._pipeline.session(reporting=True).timeout.total == 3.0, "the configured timeout was ignored"

    reporting.blocked = False
    await wait_until_delivered()
    assert len(reporting.sent) >= 5, "reporting did not recover once the bookkeeper answered"


# ---------------------------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshots_of_one_task_are_delivered_in_order(reporting):
    """The newer snapshot of a task must not arrive before the older one (``/update-task`` is
    last-write-wins)."""
    # The older snapshot is the slow request: delivered independently, it would land second.
    reporting.delays["update-task"] = lambda kwargs: 0.2 if kwargs["json"]["snapshot"] == "old" else 0.0

    monitor.post("update-task", json={"id": "task-order", "snapshot": "old"})
    monitor.post("update-task", json={"id": "task-order", "snapshot": "new"})

    await wait_until_delivered()
    assert [kwargs["json"]["snapshot"] for _, kwargs in reporting.sent] == ["old", "new"]


@pytest.mark.asyncio
async def test_event_time_is_stamped_at_submission_not_at_delivery(reporting):
    """A backlogged queue must not turn into back-dated events.

    The event under test waits behind a slow one, so submission and delivery are far enough apart to
    tell the two stamps apart.
    """
    reporting.delays["task-event"] = lambda kwargs: 0.3 if kwargs["data"]["task_id"] == "blocker" else 0.0

    before = time.time()
    monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "blocker", 1, "", "the slow one ahead")
    monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "task-stamped", 1, "", "x")
    submitted_at = time.time()

    await wait_until_delivered()
    stamped = reporting.payload("task-stamped")["time"].timestamp()
    delivered_at = reporting.delivered_at["task-stamped"]

    assert before - 0.05 <= stamped <= submitted_at + 0.05, "not stamped at submission"
    assert delivered_at - stamped >= 0.2, "stamped at delivery"


@pytest.mark.parametrize("outcome", ["refused", "exception"])
@pytest.mark.asyncio
async def test_one_failing_event_does_not_stop_the_ones_behind_it(reporting, outcome):
    failing = "register-series"
    if outcome == "refused":
        reporting.reject_for.append(failing)   # answered, but not with success
    else:
        reporting.raise_for.append(failing)    # an event the consumer cannot send

    monitor.send_register_series({"SeriesInstanceUID": outcome})
    monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "task-after", 1, "", "accepted")

    await wait_until_delivered()
    assert reporting.endpoints() == ["task-event"], "one bad event stopped reporting"


# ---------------------------------------------------------------------------------------------
# Connection pools
# ---------------------------------------------------------------------------------------------

class RecordingSession:
    """A stand-in for ``aiohttp.ClientSession`` that records how often one is created."""

    created: List["RecordingSession"] = []

    def __init__(self, *args, **kwargs):
        RecordingSession.created.append(self)
        self.kwargs = kwargs
        self.closed = False

    def post(self, url, **kwargs):
        return _EmptyContext(_Response())

    async def close(self) -> None:
        self.closed = True


class _Response:
    status = 200
    content_type = "application/json"


class _EmptyContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_reporting_reuses_one_http_client_for_all_events(monkeypatch):
    """One client per process on the reporting pool - not one per event - closed at shutdown."""
    monkeypatch.setattr(monitor, "_pipeline", None)
    RecordingSession.created = []
    monkeypatch.setattr(aiohttp, "ClientSession", RecordingSession)
    monkeypatch.setattr(monitor, "api_key", "test-key")
    monkeypatch.setattr(monitor, "bookkeeper_address", "http://bookkeeper:8080")

    submit_events(10)
    assert await monitor.shutdown(3.0)

    assert len(RecordingSession.created) == 1, f"{len(RecordingSession.created)} clients for 10 events"
    client = RecordingSession.created[0]
    assert client.kwargs["connector"].limit_per_host == monitor.REPORTING_POOL_LIMIT
    assert client.closed, "shutdown left the pool open"


@pytest.mark.asyncio
async def test_reporting_has_its_own_pool_and_an_overall_deadline(reporting):
    """Telemetry must not crowd out the queue UI, and must not be able to hang a request."""
    pipeline = monitor._get_pipeline()
    reports = pipeline.session(reporting=True)
    reads = pipeline.session()

    assert reports is not reads, "telemetry and interactive reads share one connection pool"
    assert reports.connector.limit_per_host < reads.connector.limit_per_host
    assert reports.timeout.total is not None and reports.timeout.total <= 30, "reports have no deadline"


@pytest.mark.asyncio
async def test_interactive_reads_keep_the_default_timeouts(reporting):
    """The configured report deadline must not cut short slow queue-UI reads."""
    reads = monitor._get_pipeline().session()
    assert reads.timeout == aiohttp.client.DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shutdown_delivers_everything_queued(reporting):
    submit_events(20)
    assert await monitor.shutdown(5.0) is True
    assert len(reporting.sent) == 20


@pytest.mark.asyncio
async def test_a_shutdown_that_gives_up_is_bounded_and_stays_closed(bookkeeper, caplog):
    """Against a hung bookkeeper shutdown returns within its deadline, says so, and refuses later events."""
    bookkeeper.hang_for.append("task-event")
    submit_events(10)

    started = time.monotonic()
    with caplog.at_level(logging.ERROR):
        assert await monitor.shutdown(0.3) is False
        assert time.monotonic() - started < 3.0, "shutdown did not respect its own deadline"
        monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "task-too-late", 1, "", "x")

    assert monitor._pipeline.consumer.done(), "the consumer survived shutdown"
    assert not bookkeeper.sent
    assert any("did not drain" in m for m in log_messages(caplog)), "lost silently"
    assert any("shut down" in m for m in log_messages(caplog)), "refused silently"


def test_events_from_work_that_finishes_during_shutdown_are_still_delivered(bookkeeper, service_loop):
    """Reporting is drained last, so work finishing during shutdown can still report."""
    async def finishing_job() -> None:
        await asyncio.sleep(0.05)
        monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "task-last-gasp", 1, "", "finished")

    service_loop.create_task(finishing_job())
    helper.drain_pending_tasks(service_loop, monitor_timeout=2.0, task_timeout=2.0)
    reported = [kwargs.get("data", {}).get("task_id") for _, kwargs in bookkeeper.sent]
    assert "task-last-gasp" in reported, "the pipeline closed before work finishing on shutdown reported"


def test_the_shutdown_drain_returns_within_its_deadline_and_cancels_the_rest(bookkeeper, service_loop, caplog):
    """The service must hand back inside its deadline and cancel what is left."""
    bookkeeper.hang_for.append("task-event")
    monitor.send_task_event(monitor.task_event.PROCESS_COMPLETE, "task-1", 1, "", "x")
    never_finishes = service_loop.create_task(asyncio.sleep(3600))

    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        helper.drain_pending_tasks(service_loop, monitor_timeout=0.5, task_timeout=0.5)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"the shutdown drain took {elapsed:.1f}s; systemd would have killed the service"
    assert not bookkeeper.sent
    assert any("did not drain" in m for m in log_messages(caplog)), "undelivered reports went unmentioned"
    assert any("Cancelling 1 task" in m for m in log_messages(caplog))
    assert never_finishes.cancelled(), "in-flight work was neither awaited nor cancelled"
    assert not [t for t in asyncio.all_tasks(service_loop) if not t.done()], "tasks left pending"


def test_the_shutdown_drain_refuses_a_running_loop(bookkeeper):
    """The synchronous drain must not re-enter a live loop; async paths await ``monitor.shutdown()``."""
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="after the event loop has stopped"):
            loop.run_until_complete(_call_drain_on_running_loop())
    finally:
        loop.close()


async def _call_drain_on_running_loop() -> None:
    helper.drain_pending_tasks(asyncio.get_running_loop(), monitor_timeout=0.1, task_timeout=0.1)


def test_events_submitted_before_the_loop_starts_are_delivered(bookkeeper, service_loop):
    """Every service sends ``BOOT`` from ``main()`` before the loop runs; it must not be lost."""
    monitor.send_event(monitor.m_events.BOOT, description=f"pid test {uuid.uuid4()}")
    assert monitor._pipeline.queue.qsize() == 1, "no queue exists before the event loop starts"
    assert service_loop.run_until_complete(monitor.shutdown(2.0)), "the queued boot event was not delivered"
    assert "mercure-event" in bookkeeper.endpoints()
