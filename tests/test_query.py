import os
from pathlib import Path
import tempfile
import pydicom
import pytest
from pynetdicom import AE, evt, StoragePresentationContexts, build_role
from pynetdicom.sop_class import Verification, StudyRootQueryRetrieveInformationModelFind, StudyRootQueryRetrieveInformationModelGet,PatientRootQueryRetrieveInformationModelGet,  CTImageStorage # type: ignore
from pynetdicom.status import Status
from pydicom.uid import generate_uid
from pydicom.dataset import Dataset, FileMetaDataset
from rq import Worker
from webinterface.dashboards.query import GetAccessionJob, SimpleDicomClient, WrappedJob
from common.types import DicomTarget, DicomWebTarget
from webinterface.common import redis, worker_queue

from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian
from testing_common import receiver_port, mercure_config
from logging import getLogger
from rq import SimpleWorker, Queue
from fakeredis import FakeStrictRedis

getLogger('pynetdicom').setLevel('WARNING')
# Mock data for testing
MOCK_ACCESSION = "12345"

@pytest.fixture(scope="module")
def mock_node(receiver_port):
    return DicomTarget(ip="127.0.0.1", port=str(receiver_port), aet_target="TEST")

class DummyDICOMServer:
    """A simple DICOM server for testing purposes."""
    def __init__(self, port:int, dataset:Dataset):
        assert isinstance(port, int), "Port must be an integer"
        assert isinstance(dataset, Dataset), "Dataset must be a pydicom Dataset"
        self.ae = AE()
        # Add support for DICOM verification
        self.ae.add_supported_context(Verification)
        self.dataset = dataset
        # Define handler for C-FIND requests
        def handle_find(event):
            ds = event.identifier

            # Create a dummy response
            # Check if the request matches our dummy data
            if 'AccessionNumber' in ds and ds.AccessionNumber == MOCK_ACCESSION:
                yield (0xFF00, self.dataset)
            else:
                yield (0x0000, None)  # Status 'Success', but no match

        # Define handler for C-GET requests
        def handle_get(event):
            ds = event.identifier
            # yield 1
            # Check if the request matches our dummy data
            if 'AccessionNumber' in ds and ds.AccessionNumber == MOCK_ACCESSION:
                # Create a dummy DICOM dataset
                yield 1

                dummy_ds = self.dataset.copy()
                dummy_ds.SOPClassUID = CTImageStorage  # CT Image Storage
                dummy_ds.SOPInstanceUID = generate_uid()
                dummy_ds.file_meta = FileMetaDataset()
                dummy_ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

                # Yield the dataset
                yield (0xFF00, dummy_ds)
            else:
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
def dummy_dataset():
    ds = Dataset()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "12345"
    ds.StudyDescription = "Test Study"
    ds.StudyDate = "20210101"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.AccessionNumber = MOCK_ACCESSION
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds

@pytest.fixture(scope="function")
def dicom_server(mock_node, dummy_dataset):
    """
    Pytest fixture to start a DICOM server before tests and stop it after.
    This fixture has module scope, so the server will be started once for all tests in the module.
    """
    server = DummyDICOMServer(int(mock_node.port), dummy_dataset)
    yield mock_node
    server.stop()

@pytest.fixture(scope="function")
def dicomweb_server(dummy_dataset, tempdir):
    ds = dummy_dataset.copy()
    ds.SOPClassUID = CTImageStorage  # CT Image Storage
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    
    (tempdir / "dicomweb").mkdir()
    ds.save_as(tempdir / "dicomweb" / "dummy.dcm", write_like_original=False)

    yield DicomWebTarget(url=f"file://{tempdir}/dicomweb")

def test_simple_dicom_client(dicom_server):
    """Test the SimpleDicomClient can connect to and query the DICOM server."""
    client = SimpleDicomClient(dicom_server.ip, dicom_server.port, dicom_server.aet_target, None)

    result = client.findscu(MOCK_ACCESSION)
    assert result is not None  # We expect some result, even if it's an empty dataset
    assert result[0].AccessionNumber == MOCK_ACCESSION  # Check if the accession number matches

@pytest.fixture(scope="function")
def tempdir():
    with tempfile.TemporaryDirectory(prefix="mercure_temp") as d:
        yield Path(d)

def test_get_accession_job(dicom_server, dicomweb_server, mercure_config):
    """Test the get_accession_job function."""
    config = mercure_config()
    job_id = "test_job"
    
    for server,job in ((dicom_server, GetAccessionJob), (dicomweb_server, GetAccessionJob)):
        generator = GetAccessionJob.get_accession(job_id, MOCK_ACCESSION, server, config.jobs_folder)
        results = list(generator)
        # Check that we got some results
        assert len(results) > 0
        assert results[0].remaining == 0
        assert pydicom.dcmread(next(k for k in Path(config.jobs_folder).iterdir())).AccessionNumber == MOCK_ACCESSION

def test_query_job(dicom_server, tempdir):
    """
    Test the create_job function.
    We use mocker to mock the queue and avoid actually creating jobs.
    """
    queue = Queue(connection=redis)
    job = WrappedJob.create([MOCK_ACCESSION], dicom_server, str(tempdir), queue=queue)
    assert job
    w = SimpleWorker([queue], connection=redis)
    w.work(burst=True)
    # assert len(list(Path(config.mercure.jobs_folder).iterdir())) == 1
    print([k for k in Path(tempdir).rglob('*')])
    assert pydicom.dcmread(next(k for k in Path(tempdir).rglob("*.dcm"))).AccessionNumber == MOCK_ACCESSION

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

def test_query_dicomweb(dicomweb_server, tempdir, dummy_dataset, fs):
    (tempdir / "outdir").mkdir()
    queue = Queue(connection=redis)
    wrapped_job = WrappedJob.create([MOCK_ACCESSION], dicomweb_server, (tempdir / "outdir"), queue=queue)
    assert wrapped_job
    w = SimpleWorker([queue], connection=redis)
    w.work(burst=True)
    # tree(tempdir / "outdir")
    outfile = (tempdir / "outdir" / wrapped_job.id / dummy_dataset.AccessionNumber /  f"{dummy_dataset.SOPInstanceUID}.dcm")
    assert outfile.exists(), f"File {outfile} does not exist."
    wrapped_job.get_meta()
    assert wrapped_job.meta['completed'] == 1
    assert wrapped_job.meta['total'] == 1