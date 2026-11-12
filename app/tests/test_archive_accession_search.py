"""
test_archive_accession_search.py
================================
Regression tests for "corrected accession not searchable in Archive".

Scenario from the report: a study is routed with AccessionNumber A, corrected to
B in the source system (same Study/Series Instance UIDs) and sent again. The
re-send is dispatched with B, but in Queue -> Job List -> Archive a search for B
finds nothing and a search for A shows both jobs.

Why: ``dicom_series.series_uid`` is unique and ``register_series()`` swallows the
unique violation, so the series row keeps A forever, and ``find_task()`` searches
and displays the tags of that row.

Nothing here copies product logic:

  * rows are written by the REAL bookkeeper endpoints
    (``/register-series``, ``/register-task``, ``/update-task`` handlers called
    in-process against a real PostgreSQL - pg0-embedded),
  * task payloads are built by the REAL ``compose_task()``,
  * assertions run the REAL ``find_task()`` / ``get_task_info()`` handlers.

What the tests DO own is the router's call sequence (documented in
``route_series_level`` / ``route_study_level``); for the series-level case that
sequence is independently pinned by tests/integration/test_archive_accession.py,
which runs the actual router as separate processes.

Coverage beyond the integration test: study-level routing (incl. the
"studies only" filter and the documented per-series-row fallback), the
get_task_info popup, ACC-column sorting, and the dicom_series fallback for
tasks without a snapshot - all without supervisord/dcmsend and without the
TEST_FAST skip, in a few seconds.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import pytest
import pytest_asyncio
import sqlalchemy
from common.types import Rule, Task

pytest.importorskip("pg0")
pytest.importorskip("databases")

ACC_A = "ACCA12345"
ACC_B = "ACCB99999"
MRN = "MRN-007"
NAME = "DOE^JOHN"

RULES = {
    "rules": {
        "route_series": Rule(
            rule='tags.SeriesDescription == "series-level"',
            action="route",
            target="test_target",
            action_trigger="series",
        ).dict(),
        "route_study": Rule(
            rule='tags.SeriesDescription == "study-level"',
            action="route",
            target="test_target_2",
            action_trigger="study",
        ).dict(),
    }
}

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- database


@pytest.fixture(scope="module")
def pg0_url():
    """Start one fresh embedded PostgreSQL per module; yield its DSN."""
    from pg0 import Pg0

    pg = Pg0(name=f"mercure-archive-{uuid.uuid4().hex[:8]}")
    try:
        info = pg.start()
    except Exception as exc:  # infra problem, not a product bug: skip, don't fail red
        pytest.skip(f"pg0 could not be started in this environment: {exc}")
    try:
        yield info.uri
    finally:
        pg.drop()


@pytest_asyncio.fixture
async def bookkeeper_db(pg0_url, monkeypatch, mercure_config):
    """Bind bookkeeping.database to the embedded PostgreSQL with the real table DDL."""
    import bookkeeping.config as bk_config
    import bookkeeping.database as db
    import databases

    mercure_config(RULES)
    bk_config.read_bookkeeper_config()
    db.init_database(pg0_url)
    database = databases.Database(pg0_url)
    await database.connect()
    monkeypatch.setattr(db, "database", database)

    dialect = sqlalchemy.dialects.postgresql.dialect()
    # Fresh tables per test: each test seeds the same ids.
    for name in ("tasks", "dicom_series"):
        await database.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    for table in (db.tasks_table, db.dicom_series):
        await database.execute(str(sqlalchemy.schema.CreateTable(table).compile(dialect=dialect)))
    try:
        yield database
    finally:
        await database.disconnect()


# --------------------------------------------------------------- calling real endpoints


async def call(endpoint, *, path: str, query: Optional[Dict[str, str]] = None,
               json_body=None, form=None):
    """Invoke a real (auth-decorated) endpoint handler with a constructed Request.

    ``@requires("authenticated")`` is enforced by middleware on the deployed app,
    not by the decorated function itself, so ``__wrapped__`` is the actual handler.
    """
    from starlette.requests import Request

    body = b""
    headers = []
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers = [(b"content-type", b"application/json")]
    elif form is not None:
        body = urlencode(form).encode()
        headers = [(b"content-type", b"application/x-www-form-urlencoded")]

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST" if (json_body or form) else "GET",
        "path": path, "raw_path": path.encode(),
        "query_string": urlencode(query or {}).encode(),
        "headers": headers + [(b"content-length", str(len(body)).encode())],
        "client": ("test", 1), "server": ("test", 80), "scheme": "http",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    response = await endpoint.__wrapped__(Request(scope, receive=receive))
    return json.loads(response.body.decode()) if getattr(response, "body", None) else None


# --------------------------------------------------- the router's calls, one send at a time


@dataclass
class Send:
    parent_id: str           # the router's task_id: the row the Archive lists
    job_id: str              # child (series-level) or study task (study-level)


def _tags(series_uid: str, study_uid: str, acc: Optional[str], description: str) -> Dict[str, str]:
    tags = {
        "SeriesInstanceUID": series_uid,
        "StudyInstanceUID": study_uid,
        "PatientID": MRN,
        "PatientName": NAME,
        "SeriesDescription": description,
    }
    if acc is not None:
        tags["AccessionNumber"] = acc
    return tags


def _sample_tags(acc: str) -> Dict[str, Any]:
    """What send_update_task_tags posts: dcmread(...).to_json_dict() of the first slice."""
    import pydicom

    ds = pydicom.Dataset()
    ds.AccessionNumber = acc
    ds.PatientID = MRN
    ds.PatientName = NAME
    return ds.to_json_dict()


async def route_series_level(bookkeeper_db, series_uid: str, study_uid: str, acc: Optional[str],
                             sample_tags: bool = False) -> Send:
    """The bookkeeper calls route_series() + push_serieslevel_outgoing() makes:

    register-task (parent, no data) [ -> update-task {"id","tags"} if
    store_sample_dicom_tags] -> register-series -> update-task (full Task for the
    hand-off child, carrying info.acc of THIS send) -> register-task (child,
    parent_id=parent).
    """
    from bookkeeping.bookkeeper import register_series, register_task, update_task
    from routing.generate_taskfile import compose_task

    tags = _tags(series_uid, study_uid, acc, "series-level")
    parent, child = f"task-{uuid.uuid4().hex[:8]}", f"task-{uuid.uuid4().hex[:8]}"

    await call(register_task, path="/register-task",
               json_body={"id": parent, "series_uid": series_uid})           # route_series:41
    if sample_tags:                                                            # route_series:94
        await call(update_task, path="/update-task",
                   json_body={"id": parent, "tags": _sample_tags(acc)})
    await call(register_series, path="/register-series", form=tags)            # route_series:117
    task = compose_task(child, series_uid, "series", {"route_series": True}, "", tags, "test_target")
    await call(update_task, path="/update-task", json_body=task.dict())       # create_series_task
    await call(register_task, path="/register-task",
               json_body={"id": child, "series_uid": series_uid, "parent_id": parent})
    return Send(parent, child)


async def route_study_level(bookkeeper_db, series_uid: str, study_uid: str,
                            acc: Optional[str]) -> Send:
    """route_series() + push_series_studylevel() for the first series of a study.

    Note update-task never sets parent_id, so the study task is a top-level row
    of its own, with info but no link to the series row (that gap is the
    documented limitation pinned by
    test_study_level_series_row_falls_back_to_first_accession).
    """
    from bookkeeping.bookkeeper import register_series, register_task, update_task
    from routing.generate_taskfile import compose_task

    tags = _tags(series_uid, study_uid, acc, "study-level")
    parent, study_task = f"task-{uuid.uuid4().hex[:8]}", f"task-{uuid.uuid4().hex[:8]}"

    await call(register_task, path="/register-task",
               json_body={"id": parent, "series_uid": series_uid})            # route_series:41
    await call(register_series, path="/register-series", form=tags)            # route_series:117
    task = compose_task(study_task, study_uid, "study", {"route_study": True}, "route_study", tags, "")
    await call(update_task, path="/update-task", json_body=task.dict())       # create_study_task
    return Send(parent, study_task)


# ------------------------------------------------------------------------- the Archive UI


async def archive_search(search: str, *, order_column: str = "4", order_dir: str = "desc",
                         study_filter: bool = False) -> Dict[str, Any]:
    """What the Archive tab requests: /api/find-tasks -> find_task()."""
    import bookkeeping.query as query

    return await call(query.find_task, path="/find_task", query={
        "draw": "1", "start": "0", "length": "50", "search[value]": search,
        "order[0][column]": order_column, "order[0][dir]": order_dir,
        "study_filter": "true" if study_filter else "false",
    })


async def job_information(task_id: str) -> Dict[str, Any]:
    """The 'Job information' popup: get_task_info()."""
    import bookkeeping.query as query

    return await call(query.get_task_info, path="/get_task_info", query={"task_id": task_id})


def acc_by_task(payload: Dict[str, Any]) -> Dict[str, str]:
    return {row["task_id"]: row["ACC"] for row in payload["data"]}


# --------------------------------------------------------------------------- sanity checks


async def test_seed_matches_what_mercure_writes(bookkeeper_db):
    """Guards the seed itself: the listed row has no info, the per-send snapshot lives elsewhere."""
    sent = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A)
    rows = {r["id"]: dict(r) for r in await bookkeeper_db.fetch_all("SELECT * FROM tasks")}

    assert rows[sent.parent_id]["parent_id"] is None and rows[sent.parent_id]["data"] is None
    assert rows[sent.job_id]["parent_id"] == sent.parent_id
    Task(**json.loads(rows[sent.job_id]["data"]))  # the stored payload is a real Task
    assert json.loads(rows[sent.job_id]["data"])["info"]["acc"] == ACC_A

    study = await route_study_level(bookkeeper_db, "1.2.4.1", "1.2.4", ACC_A)
    rows = {r["id"]: dict(r) for r in await bookkeeper_db.fetch_all("SELECT * FROM tasks")}
    assert rows[study.job_id]["parent_id"] is None, "update-task never sets parent_id"
    assert rows[study.job_id]["study_uid"] == "1.2.4"
    assert json.loads(rows[study.job_id]["data"])["info"]["uid_type"] == "study"


# ---------------------------------------------------------------------- series-level re-send


async def test_series_level_resend_is_findable_under_corrected_accession(bookkeeper_db):
    """Report steps 1-4 with a series-level rule: search for B must find the re-send."""
    first = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A)
    resend = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_B)

    found = acc_by_task(await archive_search(ACC_B))
    assert found == {resend.parent_id: ACC_B}, f"search {ACC_B}: expected only the re-send, got {found}"

    found = acc_by_task(await archive_search(ACC_A))
    assert found == {first.parent_id: ACC_A}, f"search {ACC_A}: expected only the first send, got {found}"


async def test_series_level_resend_with_sample_tags_stored(bookkeeper_db):
    """Same, with store_sample_dicom_tags on: the parent row then carries data, but still no info."""
    first = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A, sample_tags=True)
    resend = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_B, sample_tags=True)

    assert acc_by_task(await archive_search(ACC_B)) == {resend.parent_id: ACC_B}
    assert acc_by_task(await archive_search(ACC_A)) == {first.parent_id: ACC_A}


async def test_series_level_job_information_shows_sent_accession(bookkeeper_db):
    first = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A)
    resend = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_B)

    assert (await job_information(resend.parent_id))["information"]["AccessionNumber"] == ACC_B
    assert (await job_information(first.parent_id))["information"]["AccessionNumber"] == ACC_A


async def test_series_level_sorting_by_acc_uses_sent_accession(bookkeeper_db):
    """Sorting by the ACC column must order on the same value the column shows."""
    # Resend first in time, so that time order and ACC order disagree.
    resend = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_B)
    first = await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A)

    payload = await archive_search("", order_column="0", order_dir="asc")
    shown = [(row["task_id"], row["ACC"]) for row in payload["data"]]
    assert shown == [(first.parent_id, ACC_A), (resend.parent_id, ACC_B)], shown


# ----------------------------------------------------------------------- study-level re-send


async def test_study_level_resend_is_findable_under_corrected_accession(bookkeeper_db):
    """Report steps 1-4 with a study-level rule: the re-sent study job must be found under B."""
    first = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_A)
    resend = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_B)

    found = acc_by_task(await archive_search(ACC_B))
    assert found.get(resend.job_id) == ACC_B, f"search {ACC_B}: re-sent study job missing, got {found}"
    assert first.job_id not in found

    found = acc_by_task(await archive_search(ACC_A))
    assert found.get(first.job_id) == ACC_A
    assert resend.job_id not in found, f"search {ACC_A}: re-sent study job shown under old accession: {found}"


async def test_study_level_resend_with_study_filter(bookkeeper_db):
    """The Archive's 'studies only' filter lists the study tasks themselves."""
    first = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_A)
    resend = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_B)

    assert acc_by_task(await archive_search(ACC_B, study_filter=True)) == {resend.job_id: ACC_B}
    assert acc_by_task(await archive_search(ACC_A, study_filter=True)) == {first.job_id: ACC_A}


async def test_study_level_series_row_falls_back_to_first_accession(bookkeeper_db):
    """Known limitation, pinned deliberately: the per-series row of a study-level send
    shows the FIRST accession of the series.

    That row has no info, no children and no link to the study task (update-task never
    sets parent_id), so no per-send value exists anywhere for the query to find. Making
    it follow the corrected accession requires a product change (e.g. route_series
    linking the study task to the series row), not a query change.
    """
    first = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_A)
    resend = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_B)

    found_b = acc_by_task(await archive_search(ACC_B))
    assert found_b == {resend.job_id: ACC_B}, "only the study task itself carries the corrected value"

    found_a = acc_by_task(await archive_search(ACC_A))
    assert found_a[resend.parent_id] == ACC_A, "re-send's series row falls back to dicom_series"
    assert found_a[first.parent_id] == ACC_A
    assert found_a[first.job_id] == ACC_A
    assert resend.job_id not in found_a


async def test_study_level_job_information_shows_sent_accession(bookkeeper_db):
    first = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_A)
    resend = await route_study_level(bookkeeper_db, "1.2.5.1", "1.2.5", ACC_B)

    assert (await job_information(resend.job_id))["information"]["AccessionNumber"] == ACC_B
    assert (await job_information(first.job_id))["information"]["AccessionNumber"] == ACC_A


# -------------------------------------------------------------------------------- guards


async def test_task_without_snapshot_falls_back_to_series_row(bookkeeper_db):
    """A task that was registered but never updated (data NULL) shows dicom_series' value."""
    import bookkeeping.bookkeeper as bk

    await call(bk.register_series, path="/register-series", form=_tags("1.2.8.1", "1.2.8", ACC_A, "g"))
    await call(bk.register_task, path="/register-task", json_body={"id": "job-no-data", "series_uid": "1.2.8.1"})

    assert acc_by_task(await archive_search(ACC_A)) == {"job-no-data": ACC_A}


async def test_missing_placeholder_snapshot_falls_back_to_series_row(bookkeeper_db):
    """A send whose tags carry no AccessionNumber stores the "MISSING" placeholder, which
    must not mask the dicom_series fallback."""
    # Send 1 registers the series with a real accession; the "corrected" re-send omits
    # AccessionNumber entirely, so compose_task() stores mercure's MISSING placeholder.
    await route_series_level(bookkeeper_db, "1.2.9.1", "1.2.9", ACC_A)
    resend = await route_series_level(bookkeeper_db, "1.2.9.1", "1.2.9", None)

    found = acc_by_task(await archive_search(ACC_A))
    assert found[resend.parent_id] == ACC_A, "MISSING snapshot must fall back, not display MISSING"
    assert acc_by_task(await archive_search(ACC_B)) == {}


async def test_unrelated_series_keep_their_own_accession(bookkeeper_db):
    """No re-send: every job shows and is found under its own accession."""
    a = await route_series_level(bookkeeper_db, "1.2.6.1", "1.2.6", ACC_A)
    b = await route_series_level(bookkeeper_db, "1.2.7.1", "1.2.7", ACC_B)

    assert acc_by_task(await archive_search(ACC_A)) == {a.parent_id: ACC_A}
    assert acc_by_task(await archive_search(ACC_B)) == {b.parent_id: ACC_B}


async def test_unmatched_search_stays_empty(bookkeeper_db):
    await route_series_level(bookkeeper_db, "1.2.3.1", "1.2.3", ACC_A)
    payload = await archive_search("NO-SUCH-ACCESSION")
    assert payload["data"] == [] and payload["recordsFiltered"] == 0
