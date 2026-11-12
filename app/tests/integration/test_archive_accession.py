"""
test_archive_accession.py
=========================
End-to-end regression for "corrected accession not searchable in Archive".

A series is received and routed to a target under AccessionNumber A; the same
series is then re-sent with the same Study/Series Instance UIDs and corrected
AccessionNumber B. Both sends must be dispatched, and the Archive tab
(bookkeeper /query/find_task) must show each job under the accession it was
actually sent with.

Unlike test_archive_accession_search.py, nothing here is seeded: real receiver,
real router, real dispatcher, real bookkeeper over a real PostgreSQL
(pg0-embedded; the SQLite default cannot run find_task()'s Postgres SQL).
"""

import tempfile
import uuid
from pathlib import Path

import pydicom
import pytest
import requests
from common.types import FolderTarget, Rule
from pydicom.uid import generate_uid

from app.tests.integration.common import send_dicom, wait_for
from tests.testing_common import create_minimal_dicom

ACC_A = "ACCA12345"
ACC_B = "ACCB99999"

AUTH = {"Authorization": "Token test"}

pytestmark = pytest.mark.skipif("os.getenv('TEST_FAST', False)")


@pytest.fixture(scope="module")
def pg_uri():
    """One embedded PostgreSQL for the module; the bookkeeper runs against it."""
    from pg0 import Pg0

    pg = Pg0(name=f"mercure-integration-{uuid.uuid4().hex[:8]}")
    try:
        info = pg.start()
    except Exception as exc:  # infra problem, not a product bug: skip, don't fail red
        pytest.skip(f"pg0 could not be started in this environment: {exc}")
    try:
        yield info.uri
    finally:
        pg.drop()


def find_task(bookkeeper_port: int, search: str):
    """What the Archive tab does: /api/find-tasks -> bookkeeper /query/find_task."""
    response = requests.get(
        f"http://localhost:{bookkeeper_port}/query/find_task",
        headers=AUTH,
        params={"draw": 1, "start": 0, "length": 50, "search[value]": search,
                "order[0][column]": "4", "order[0][dir]": "desc", "study_filter": "false"},
    )
    assert response.status_code == 200, f"find_task failed: {response.status_code} {response.text}"
    return response.json()


def dispatched_accessions(target_folder) -> dict:
    """SOPInstanceUID -> AccessionNumber of every file that reached the dispatch target."""
    found = {}
    for f in target_folder.rglob("*.dcm"):
        ds = pydicom.dcmread(f, stop_before_pixels=True)
        found[ds.SOPInstanceUID] = ds.AccessionNumber
    return found


def dump_bookkeeper_state(pg_uri, *queries, path=None):
    """Write DB state + archive responses to /tmp/archive_debug.txt for post-mortem."""
    import asyncio

    import asyncpg

    async def _dump():
        con = await asyncpg.connect(pg_uri)
        rows = await con.fetch("SELECT id, parent_id, series_uid, left(data::text, 200) d FROM tasks ORDER BY id")
        series = await con.fetch("SELECT series_uid, tag_accessionnumber FROM dicom_series")
        events = await con.fetch("SELECT task_id, event, target, info FROM task_events ORDER BY id")
        await con.close()
        with open(path or Path(tempfile.gettempdir()) / "mercure_archive_debug.txt", "w") as fp:
            for r in rows:
                fp.write(f"TASK {dict(r)}\n")
            for r in series:
                fp.write(f"SERIES {dict(r)}\n")
            for r in events:
                fp.write(f"EVENT {dict(r)}\n")
            for q in queries:
                fp.write(f"QUERY {q}\n")

    asyncio.run(_dump())


def test_corrected_accession_findable_in_archive(mercure, mercure_config, mercure_base,
                                                 receiver_port, bookkeeper_port, pg_uri):
    config = {
        "rules": {
            "to_archive": Rule(
                rule="True", action="route", action_trigger="series", target="archive"
            ).dict(),
        },
        "targets": {"archive": FolderTarget(folder=str(mercure_base / "target")).dict()},
    }
    mercure_config(config)
    # The bookkeeper fixture configures SQLite, which cannot run find_task()'s SQL.
    (mercure_base / "config" / "bookkeeper.env").write_text(
        f"PORT={bookkeeper_port}\nHOST=0.0.0.0\nDATABASE_URL={pg_uri}\nDEBUG=True\n"
    )
    (mercure_base / "target").mkdir(parents=True, exist_ok=True)
    mercure(["bookkeeper", "receiver", "router:*", "dispatcher:*"])

    study_uid, series_uid = generate_uid(), generate_uid()
    tags = {"StudyInstanceUID": study_uid, "SeriesInstanceUID": series_uid,
            "PatientID": "MRN-007", "PatientName": "DOE^JOHN"}

    def dispatched(ds, acc: str):
        # wait_for retries while fn() RAISES AssertionError; a lambda returning
        # False would never block.
        got = dispatched_accessions(mercure_base / "target")
        assert got.get(ds.SOPInstanceUID) == acc, f"{ds.SOPInstanceUID} not dispatched with {acc}: {got}"

    # --- Send 1 under accession A ------------------------------------------------
    ds_a = create_minimal_dicom(None, series_uid, {**tags, "AccessionNumber": ACC_A})
    send_dicom(ds_a, "localhost", receiver_port)
    wait_for(lambda: dispatched(ds_a, ACC_A), timeout=60,
             msg="first send never reached the dispatch target")

    def first_send_listed():
        rows = find_task(bookkeeper_port, ACC_A)["data"]
        assert rows and all(row["ACC"] == ACC_A for row in rows), (
            f"first send should be listed under {ACC_A} showing {ACC_A}: {rows}")

    wait_for(first_send_listed, timeout=30, msg="first send not listed in Archive under A")

    # --- Send 2: same UIDs, corrected accession B --------------------------------
    # The Archive state above proves send 1 is a completed, separate job: sending
    # any earlier would let the router batch both files into one incoming scan.
    ds_b = create_minimal_dicom(None, series_uid, {**tags, "AccessionNumber": ACC_B})
    send_dicom(ds_b, "localhost", receiver_port)
    wait_for(lambda: dispatched(ds_b, ACC_B), timeout=60,
             msg="corrected re-send never reached the dispatch target")

    # --- Archive expectations ------------------------------------------------------
    # The task rows reach the bookkeeper through the router's async reporting
    # pipeline, so poll until the Archive settled into the expected state.
    # Row counts are not pinned: with several router processes a series can be
    # registered more than once (separate known race, see the empty Rule ''
    # rows). What must hold is that every job shows, and is findable under,
    # the accession it was actually sent with.
    def archive_shows_b():
        found = find_task(bookkeeper_port, ACC_B)["data"]
        assert found and all(row["ACC"] == ACC_B for row in found), (
            f"Archive search for the corrected accession {ACC_B} must find the re-sent "
            f"job showing {ACC_B}, got: {found}")

    def archive_shows_a():
        found = find_task(bookkeeper_port, ACC_A)["data"]
        assert found and all(row["ACC"] == ACC_A for row in found), (
            f"the first send must stay findable and displayed under {ACC_A}, and the "
            f"re-send must not hide under it, got: {found}")
        b_ids = {row["task_id"] for row in find_task(bookkeeper_port, ACC_B)["data"]}
        assert not (b_ids & {row["task_id"] for row in found}), (
            "the re-sent job must not be listed under the old accession")

    try:
        wait_for(archive_shows_b, timeout=30, msg=f"corrected accession {ACC_B} not findable in Archive")
        archive_shows_a()
    except Exception:
        dump_bookkeeper_state(pg_uri,
                              find_task(bookkeeper_port, ""),
                              find_task(bookkeeper_port, ACC_A),
                              find_task(bookkeeper_port, ACC_B))
        raise
