import json
import os
import subprocess
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Dict, Optional, Tuple

import pydicom
import pytest
from common.types import DicomTarget, DicomWebTarget, Rule
from fakeredis import FakeStrictRedis
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.sop_class import (CTImageStorage,  # type: ignore
                                  PatientRootQueryRetrieveInformationModelGet,
                                  StudyRootQueryRetrieveInformationModelFind,
                                  StudyRootQueryRetrieveInformationModelGet,
                                  Verification)
from pynetdicom.status import Status
from routing import router
from rq import SimpleWorker, Worker
from testing_common import bookkeeper_port, mercure_config, receiver_port
from webinterface.dashboards.query.jobs import GetAccessionTask, QueryPipeline
from webinterface.dicom_client import SimpleDicomClient

getLogger('pynetdicom').setLevel('WARNING')
# Mock data for testing
MOCK_ACCESSIONS = ["1","2","3"]


@pytest.fixture(scope="module", autouse=True)
def rq_connection():
    my_redis = FakeStrictRedis()
    # with Connection(my_redis):
    yield my_redis

@pytest.fixture(scope="module")
def mock_node(receiver_port):
    return DicomTarget(ip="127.0.0.1", port=str(receiver_port), aet_target="TEST")

class DummyDICOMServer:
    remaining_allowed_accessions: Optional[int] = None
    """A simple DICOM server for testing purposes."""
    def __init__(self, port:int, datasets: Dict[str,Dataset]):
        assert isinstance(port, int), "Port must be an integer"
        for ds in datasets.values():
            assert isinstance(ds, Dataset), "Dataset must be a pydicom Dataset"
        self.ae = AE()
        # Add support for DICOM verification
        self.ae.add_supported_context(Verification)
        self.datasets = datasets
        # Define handler for C-FIND requests
        def handle_find(event):
            ds = event.identifier

            # Create a dummy response
            # Check if the request matches our dummy data
            if 'AccessionNumber' in ds and ds.AccessionNumber in MOCK_ACCESSIONS:
                yield (0xFF00, self.datasets[ds.AccessionNumber])
            else:
                yield (0x0000, None)  # Status 'Success', but no match

        # Define handler for C-GET requests
        def handle_get(event):
            ds = event.identifier
            # yield 1
            # Check if the request matches our dummy data
            if 'AccessionNumber' in ds and ds.AccessionNumber in MOCK_ACCESSIONS \
                    and ( self.remaining_allowed_accessions is None or  self.remaining_allowed_accessions > 0 ):
                # Create a dummy DICOM dataset
                yield 1

                dummy_ds = self.datasets[ds.AccessionNumber].copy()
                dummy_ds.SOPClassUID = CTImageStorage  # CT Image Storage
                dummy_ds.SOPInstanceUID = generate_uid()
                dummy_ds.file_meta = FileMetaDataset()
                dummy_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

                # Yield the dataset
                if self.remaining_allowed_accessions:
                    self.remaining_allowed_accessions = self.remaining_allowed_accessions - 1
                yield (0xFF00, dummy_ds)
            else:
                yield 0
                yield (0x0000, None)  # Status 'Success', but no match
        # Bind the C-FIND handler


        # Add the supported presentation contexts (Storage SCU)
        self.ae.supported_contexts = StoragePresentationContexts

        for cx in self.ae.supported_contexts:
            cx.scp_role = True
            cx.scu_role = False

        # Add a supported presentation context (QR Get SCP)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)

        self.ae.start_server(("127.0.0.1", port), block=False, evt_handlers=[(evt.EVT_C_FIND, handle_find), (evt.EVT_C_GET, handle_get)])

    def stop(self)->None:
        """Stop the DICOM server."""
        self.ae.shutdown()

@pytest.fixture(scope="function")
def dummy_datasets():
    dss = {}
    for acc in MOCK_ACCESSIONS:
        ds = Dataset()
        ds.PatientName = "Test^Patient"
        ds.PatientID = "12345"
        ds.StudyDescription = "Test Study"
        ds.StudyDate = "20210101"
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.AccessionNumber = acc
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        dss[acc] = ds
    return dss

@pytest.fixture(scope="function")
def dicom_server(mock_node, dummy_datasets):
    """
    Pytest fixture to start a DICOM server before tests and stop it after.
    This fixture has module scope, so the server will be started once for all tests in the module.
    """
    server = DummyDICOMServer(int(mock_node.port), dummy_datasets)
    yield mock_node
    server.stop()

@pytest.fixture(scope="function")
def dicom_server_2(mock_node, dummy_datasets):
    """
    Pytest fixture to start a DICOM server before tests and stop it after.
    This fixture has module scope, so the server will be started once for all tests in the module.
    """
    server = DummyDICOMServer(int(mock_node.port), dummy_datasets)
    yield mock_node, server
    server.stop()


@pytest.fixture(scope="function")
def dicomweb_server(dummy_datasets, tempdir):
    (tempdir / "dicomweb").mkdir()

    for dummy_dataset in dummy_datasets.values():
        ds = dummy_dataset.copy()
        ds.SOPClassUID = CTImageStorage  # CT Image Storage
        ds.SOPInstanceUID = generate_uid()
        ds.StudyInstanceUID = generate_uid()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.save_as(tempdir / "dicomweb" / ds.SOPInstanceUID, write_like_original=False)

    yield DicomWebTarget(url=f"file://{tempdir}/dicomweb")

def test_simple_dicom_client(dicom_server):
    """Test the SimpleDicomClient can connect to and query the DICOM server."""
    client = SimpleDicomClient(dicom_server.ip, dicom_server.port, dicom_server.aet_target, dicom_server.aet_source, None)
    
    result = client.findscu(MOCK_ACCESSIONS[0])
    assert result is not None  # We expect some result, even if it's an empty dataset
    assert result[0].AccessionNumber == MOCK_ACCESSIONS[0]  # Check if the accession number matches

@pytest.fixture(scope="function")
def tempdir():
    with tempfile.TemporaryDirectory(prefix="mercure_temp") as d:
        yield Path(d)

def test_get_accession_job(dicom_server, dicomweb_server, mercure_config):
    """Test the get_accession_job function."""
    config = mercure_config()
    job_id = "test_job"
    print(config.jobs_folder)
    assert(Path(config.jobs_folder)).exists()
    (Path(config.jobs_folder) / "foo/").touch()
    for server in (dicom_server, dicomweb_server):
        
        generator = GetAccessionTask.get_accession(job_id, MOCK_ACCESSIONS[0], server, search_filters={}, path=config.jobs_folder)
        results = list(generator)
        # Check that we got some results
        assert len(results) > 0
        assert results[0].remaining == 0
        assert pydicom.dcmread(next(k for k in Path(config.jobs_folder).rglob("*.dcm"))).AccessionNumber == MOCK_ACCESSIONS[0]

def test_query_job(dicom_server, tempdir, rq_connection,fs):
    """
    Test the create_job function.
    We use mocker to mock the queue and avoid actually creating jobs.
    """
    fs.pause()
    try:
        if (subprocess.run(['systemctl', 'is-active', "mercure_worker*"],capture_output=True,text=True,check=False,
        ).stdout.strip() == 'active'):
            raise Exception("At least one mercure worker is running, stop it before running test.")
    except subprocess.CalledProcessError:
        pass
    fs.resume()
    job = QueryPipeline.create([MOCK_ACCESSIONS[0]], {}, dicom_server, str(tempdir), redis_server=rq_connection)
    w = SimpleWorker(["mercure_fast", "mercure_slow"], connection=rq_connection)

    w.work(burst=True)
    # assert len(list(Path(config.mercure.jobs_folder).iterdir())) == 1
    print([k for k in Path(tempdir).rglob('*')])
    try:
        example_dcm = next(k for k in Path(tempdir).rglob("*.dcm"))
    except StopIteration:
        raise Exception(f"No DICOM file found in {tempdir}")
    assert pydicom.dcmread(example_dcm).AccessionNumber == MOCK_ACCESSIONS[0]

def test_query_job_to_mercure(dicom_server, tempdir, rq_connection, fs, mercure_config):
    """
    Test the create_job function.
    We use mocker to mock the queue and avoid actually creating jobs.
    """
    config = mercure_config({
        "rules": {
            "rule_to_force": Rule(
                rule="False", action="route", action_trigger="series", target="dummy"
            ).dict(),
            "rule_to_ignore": Rule(
                rule="True", action="route", action_trigger="series", target="dummy"
            ).dict(),
        }
    })
    job = QueryPipeline.create([MOCK_ACCESSIONS[0]], {}, dicom_server, None, False, "rule_to_force", rq_connection)
    w = SimpleWorker(["mercure_fast", "mercure_slow"], connection=rq_connection)

    w.work(burst=True)
    # print(list(Path(config.incoming_folder).iterdir()))
    # assert len(list(Path(config.incoming_folder).iterdir())) == 1
    print([k for k in Path(config.incoming_folder).rglob('*')])
    try:
        tags_file = next(k for k in Path(config.incoming_folder).rglob("*.tags"))
    except StopIteration:
        raise Exception(f"No tags file found in {config.incoming_folder}")
    assert json.loads(tags_file.read_text()).get('mercureForceRule') == "rule_to_force"
   
    router.run_router()
    try:
        task_file = next(k for k in Path(config.outgoing_folder).rglob("*.json"))
    except StopIteration:
        print([k for k in Path(config.outgoing_folder).rglob('*')])
        raise Exception(f"No task file found in {config.outgoing_folder}")
    task_json = json.loads(task_file.read_text())
    assert ["rule_to_force"] == list(task_json.get('info',{}).get('triggered_rules').keys())
    assert task_json.get("dispatch",{}).get("target_name") == ["dummy"]


def tree(path, prefix='', level=0) -> None:
    if level==0:
        print(path)
    entries = list(os.listdir(path))
    entries = sorted(entries, key=lambda e: (e.is_file(), e.name))
    if not entries and level==0:
        print(prefix + "[[ empty ]]")
    for i, entry in enumerate(entries):
        conn = '└── ' if i == len(entries) - 1 else '├── '
        print(f'{prefix}{conn}{entry.name}')
        if entry.is_dir():
            tree(entry.path, prefix + ('    ' if i == len(entries) - 1 else '│   '), level+1)

def test_query_dicomweb(dicomweb_server, tempdir, dummy_datasets, fs, rq_connection):
    (tempdir / "outdir").mkdir()
    ds = list(dummy_datasets.values())[0]
    task = QueryPipeline.create([ds.AccessionNumber], {}, dicomweb_server, (tempdir / "outdir"), redis_server=rq_connection)
    assert task
    w = SimpleWorker(["mercure_fast", "mercure_slow"], connection=rq_connection)
    w.work(burst=True)
    # tree(tempdir / "outdir")
    outfile = (tempdir / "outdir" / task.id / ds.AccessionNumber /  f"{ds.SOPInstanceUID}.dcm")
    assert outfile.exists(), f"Expected output file {outfile} does not exist."
    task.get_meta()
    assert task.meta['completed'] == 1
    assert task.meta['total'] == 1

def test_query_operations(dicomweb_server, tempdir, dummy_datasets, fs, rq_connection):
    (tempdir / "outdir").mkdir()
    task = QueryPipeline.create([ds.AccessionNumber for ds in dummy_datasets.values()], {}, dicomweb_server, (tempdir / "outdir"), redis_server=rq_connection)
    assert task
    assert task.meta['total'] == len(dummy_datasets)
    assert task.meta['completed'] == 0
    task.pause()    
    for job in (jobs:=task.get_subjobs()):
        assert job.meta.get("paused")
        assert job.get_status() == "canceled"
    assert jobs

    w = SimpleWorker(["mercure_fast", "mercure_slow"], connection=rq_connection)
    w.work(burst=True)
    outfile = (tempdir / "outdir" / task.id)
    task.get_meta()
    assert task.meta['completed'] == 0
    assert not outfile.exists()
    task.resume()

    for job in task.get_subjobs():
        assert not job.meta.get("paused")
        assert job.get_status() == "queued"

    w.work(burst=True)
    for ds in dummy_datasets.values():
        outfile = (tempdir / "outdir" / task.id / ds.AccessionNumber /  f"{ds.SOPInstanceUID}.dcm")
        assert outfile.exists(), f"Expected output file {outfile} does not exist."
    task.get_meta()
    assert task.meta['completed'] == len(dummy_datasets)
    assert task.meta['total'] == len(dummy_datasets)

def test_query_retry(dicom_server_2: Tuple[DicomTarget,DummyDICOMServer], tempdir, dummy_datasets, fs, rq_connection):
    (tempdir / "outdir").mkdir()
    target, server = dicom_server_2
    task = QueryPipeline.create([ds.AccessionNumber for ds in dummy_datasets.values()], {}, target, (tempdir / "outdir"), redis_server=rq_connection)

    server.remaining_allowed_accessions = 1 # Only one accession is allowed to be retrieved
    w = SimpleWorker(["mercure_fast", "mercure_slow"], connection=rq_connection)
    w.work(burst=True)
    task.get_meta()
    assert task.meta['completed'] == 1
    assert task.meta['total'] == len(dummy_datasets)
    assert "Failure during retrieval" in task.meta['failed_reason']
    # Retry the query
    server.remaining_allowed_accessions = None
    task.retry()
    w.work(burst=True)
    task.get_meta()
    assert task.meta['completed'] == len(dummy_datasets)
    assert task.meta['failed_reason'] is None