"""
test_pg0_smoke.py
=================
Minimal sanity checks for the embedded-PostgreSQL test harness (pg0-embedded)
used by test_archive_accession_search.py: can we start a real PostgreSQL,
connect with the same stack the bookkeeper uses (databases + asyncpg), and rely
on the Postgres-only features find_task()'s SQL needs?

If these fail, the archive-search regression test cannot be trusted.
"""

import json

import pytest
import pytest_asyncio
import sqlalchemy

pytest.importorskip("pg0")
pytest.importorskip("databases")

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def pg0_url():
    """Start one fresh embedded PostgreSQL per module; yield its DSN."""
    import uuid

    from pg0 import Pg0

    pg = Pg0(name=f"mercure-smoke-{uuid.uuid4().hex[:8]}")
    try:
        info = pg.start()
    except Exception as exc:  # infra problem, not a product bug
        pytest.skip(f"pg0 could not be started in this environment: {exc}")
    try:
        yield info.uri
    finally:
        pg.drop()


@pytest_asyncio.fixture
async def db_conn(pg0_url):
    import databases

    database = databases.Database(pg0_url)
    await database.connect()
    try:
        yield database
    finally:
        await database.disconnect()


async def test_select_1(db_conn):
    row = await db_conn.fetch_one("SELECT 1 AS one")
    assert row["one"] == 1


async def test_named_parameters_and_pagination(db_conn):
    await db_conn.execute("CREATE TABLE smoke_a (id TEXT, n INT)")
    await db_conn.execute("INSERT INTO smoke_a VALUES ('x', 1), ('y', 2), ('z', 3)")
    rows = await db_conn.fetch_all(
        "SELECT id FROM smoke_a WHERE n >= :min_n ORDER BY id LIMIT :l OFFSET :o",
        {"min_n": 2, "l": 1, "o": 1},
    )
    assert [r["id"] for r in rows] == ["z"]


async def test_jsonb_snapshot_extraction(db_conn):
    """find_task() reads per-task tag snapshots out of a JSONB column."""
    await db_conn.execute("CREATE TABLE smoke_b (id TEXT, data JSONB)")
    await db_conn.execute(
        "INSERT INTO smoke_b VALUES (:id, :data)", {"id": "t1", "data": json.dumps({"info": {"acc": "ACC-B"}})}
    )
    row = await db_conn.fetch_one("SELECT data->'info'->>'acc' AS acc FROM smoke_b WHERE id = 't1'")
    assert row["acc"] == "ACC-B"


async def test_ilike_string_agg_bool_or(db_conn):
    """The Postgres-only constructs find_task()'s SQL depends on."""
    await db_conn.execute("CREATE TABLE smoke_c (id TEXT, flag BOOL)")
    await db_conn.execute("INSERT INTO smoke_c VALUES ('Abc', TRUE), ('abc', FALSE)")
    rows = await db_conn.fetch_all(
        "SELECT STRING_AGG(id, ', ') AS ids, bool_or(flag) AS any_flag "
        "FROM smoke_c WHERE id ILIKE :p || '%'",
        {"p": "a"},
    )
    assert rows[0]["ids"] == "Abc, abc"
    assert rows[0]["any_flag"] is True


async def test_sqlalchemy_metadata_ddl_runs(db_conn):
    """Real bookkeeper table DDL (incl. JSONB, SERIAL PK, unique constraint) applies cleanly."""
    import bookkeeping.config as bk_config
    import bookkeeping.database as bk_db

    bk_config.read_bookkeeper_config()
    # Materialises the table objects against a postgresql URL; does not connect.
    bk_db.init_database("postgresql://pg@127.0.0.1:1/pg")
    dialect = sqlalchemy.dialects.postgresql.dialect()
    for table in (bk_db.tasks_table, bk_db.dicom_series):
        await db_conn.execute(str(sqlalchemy.schema.CreateTable(table).compile(dialect=dialect)))
    await db_conn.execute(
        "INSERT INTO tasks (id, series_uid, data) VALUES (:id, :su, :data)",
        {"id": "t", "su": "s", "data": json.dumps({"info": {"acc": "A"}})},
    )
    row = await db_conn.fetch_one("SELECT data->'info'->>'acc' AS acc FROM tasks WHERE id='t'")
    assert row["acc"] == "A"
