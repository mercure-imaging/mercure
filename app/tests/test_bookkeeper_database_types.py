"""
test_bookkeeper_database_types.py
=================================

The bookkeeper maps its JSON columns to plain TEXT when it runs on SQLite
(`JSONB = Text() if 'sqlite://' in url else postgresql.JSONB` in
bookkeeping/database.py). TEXT has no bind processor, so handing SQLAlchemy a
nested dict - which is exactly what `update_task` does with the task payload -
reaches the sqlite3 driver raw and dies with

    sqlite3.InterfaceError: Error binding parameter 3 - probably unsupported type

which surfaces as a 500 from POST /update-task. Production defaults to
PostgreSQL (postgresql://mercure@localhost), where JSONB accepts the dict, so
this only bites the SQLite path: the integration test suite. It is what makes
test_case_process intermittently stall with the series stuck in dispatch state
`waiting`.

These tests pin the contract directly, without starting any service.
"""

import datetime

import pytest
import sqlalchemy
from bookkeeping import bookkeeper  # noqa: F401  - registers the module import order the app expects
from bookkeeping import config as bk_config
from bookkeeping import database as bkdb

# A trimmed version of the payload that actually failed in CI: nested dicts and
# lists several levels deep, plus None values.
TASK_PAYLOAD = {
    "id": "f3f9c575-d244-11f1-a9dd-7ced8dc219ca",
    "info": {
        "action": "both",
        "uid": "1.2.826.0.1.3680043.8.498.95236617654673407444016396127042974392",
        "uid_type": "series",
        "triggered_rules": {"test_series": True},
        "fail_stage": None,
    },
    "dispatch": {
        "target_name": ["test_target"],
        "status": {"test_target": {"state": "waiting", "time": "2026-10-27 20:28:21"}},
        "retries": None,
        "next_retry_at": None,
    },
    "process": {
        "module_name": "dummy_module",
        "module_config": {"docker_tag": "mercureimaging/mercure-dummy-processor:latest",
                          "environment": "", "settings": {}, "requires_root": False},
        "output": None,
    },
    "study": {},
    "nomad_info": None,
}


@pytest.fixture
def sqlite_tasks_table(monkeypatch):
    """Initialise the bookkeeper schema against a throwaway SQLite file, then restore
    every module global we touched so no other test sees them.

    Runs on an in-memory database. Every test under app/tests/ executes inside the
    pyfakefs filesystem installed by the autouse mercure_config fixture, so a file-based
    SQLite path would point at a directory that only exists in the fake filesystem and
    sqlite3 - real C code, not patched - would fail to open it.
    """
    saved = {name: getattr(bkdb, name, None)
             for name in ("database", "metadata", "tasks_table", "mercure_events",
                          "webgui_events", "dicom_files", "dicom_series", "task_events",
                          "file_events", "dicom_series_map", "series_sequence_data",
                          "tests_table", "processor_logs_table", "processor_outputs_table")}
    # SQLite has no schemas; init_database() falls back to the configured one when passed None.
    monkeypatch.setattr(bk_config, "DATABASE_SCHEMA", None, raising=False)

    url = "sqlite:///:memory:"
    bkdb.init_database(url=url)
    # StaticPool keeps one connection alive, otherwise the in-memory database vanishes
    # between create_all() and the queries under test.
    engine = sqlalchemy.create_engine(url, poolclass=sqlalchemy.pool.StaticPool)
    bkdb.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        for name, value in saved.items():
            setattr(bkdb, name, value)


def _update_task_values(payload):
    """The exact shape of update_values built by bookkeeper.update_task()."""
    return dict(id=payload["id"], time=datetime.datetime(2026, 10, 27, 20, 28, 21),
                data=payload, series_uid=payload["info"]["uid"])


def _upsert(engine, values):
    query = (
        sqlalchemy.dialects.sqlite.insert(bkdb.tasks_table)
        .values(**values)
        .on_conflict_do_update(index_elements=["id"], set_=values)
    )
    with engine.begin() as conn:
        conn.execute(query)


def test_tasks_data_column_accepts_nested_dict(sqlite_tasks_table):
    """update_task() stores the whole request payload in tasks.data. On SQLite that
    column must serialise a nested dict rather than hand it to sqlite3 raw."""
    engine = sqlite_tasks_table

    _upsert(engine, _update_task_values(TASK_PAYLOAD))  # raises InterfaceError today

    with engine.begin() as conn:
        stored = conn.execute(
            sqlalchemy.select(bkdb.tasks_table.c.data).where(
                bkdb.tasks_table.c.id == TASK_PAYLOAD["id"])
        ).scalar_one()

    restored = stored if isinstance(stored, dict) else __import__("json").loads(stored)
    assert restored == TASK_PAYLOAD


def test_update_task_is_repeatable_on_the_same_row(sqlite_tasks_table):
    """The upsert runs on every state change, so the same row must be re-writable -
    including when a later payload changes the shape of the nested data."""
    engine = sqlite_tasks_table

    _upsert(engine, _update_task_values(TASK_PAYLOAD))
    later = {**TASK_PAYLOAD, "dispatch": {"target_name": ["test_target"],
                                          "status": {"test_target": {"state": "done"}}}}
    _upsert(engine, _update_task_values(later))

    with engine.begin() as conn:
        rows = conn.execute(sqlalchemy.select(bkdb.tasks_table.c.id)).scalars().all()
    assert rows == [TASK_PAYLOAD["id"]]


def test_tasks_data_column_still_accepts_null(sqlite_tasks_table):
    """Whatever serialisation is added must not make an absent payload an error."""
    engine = sqlite_tasks_table

    _upsert(engine, dict(id="task-without-data", time=datetime.datetime(2026, 10, 27),
                         data=None, series_uid=None))

    with engine.begin() as conn:
        stored = conn.execute(
            sqlalchemy.select(bkdb.tasks_table.c.data).where(
                bkdb.tasks_table.c.id == "task-without-data")
        ).scalar_one()
    assert stored is None
