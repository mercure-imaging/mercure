"""Guards for the vendored copy of dicomweb_client.

The package under ``app/dicomweb_client`` replaces the ``dicomweb-client`` PyPI dependency so
that mercure does not have to carry Pillow (which it never uses). See
``app/dicomweb_client/VENDORED.md`` and ``app/dicomweb_client/MERCURE.patch``.

These tests exist so that refreshing the vendored sources cannot silently break the seam used by
``app/dispatch/target_types/dicomweb.py``, and so that the "Pillow is optional" patch cannot be
dropped unnoticed.
"""
import inspect
from pathlib import Path

import pytest
import dicomweb_client
from dicomweb_client import DICOMfileClient
from dicomweb_client.api import DICOMwebClient
from dicomweb_client.session_utils import create_session_from_user_pass
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

VENDORED_DIR = Path(__file__).resolve().parents[1] / "dicomweb_client"

# every call the dispatcher makes, with the keyword arguments it passes
MERCURE_API = {
    DICOMfileClient: {"url", "in_memory", "update_db"},
    DICOMwebClient: {"url", "qido_url_prefix", "wado_url_prefix", "stow_url_prefix", "session", "headers"},
    DICOMwebClient.set_http_retry_params: {"retry", "max_attempts", "wait_exponential_multiplier"},
    DICOMwebClient.search_for_series: {"search_filters", "get_remaining", "fields"},
    DICOMwebClient.retrieve_series: {"study_instance_uid", "series_instance_uid"},
    DICOMwebClient.store_instances: {"datasets"},
    DICOMfileClient.search_for_series: {"search_filters", "get_remaining", "fields"},
    DICOMfileClient.retrieve_series: {"study_instance_uid", "series_instance_uid"},
    DICOMfileClient.store_instances: {"datasets"},
    create_session_from_user_pass: {"username", "password"},
}


def _params(func) -> set:
    return set(inspect.signature(func).parameters)


def test_vendored_copy_is_the_one_being_imported():
    # compare strings: pyfakefs patches pathlib during parts of this test session
    assert str(Path(dicomweb_client.__file__).resolve().parent) == str(VENDORED_DIR)


def test_vendored_version_is_recorded():
    # importlib.metadata would report an unrelated installed distribution, so __version__ is
    # pinned by MERCURE.patch
    assert dicomweb_client.__version__ == "0.60.1"


@pytest.mark.parametrize("func", list(MERCURE_API), ids=lambda f: f"{f.__qualname__}")
def test_dispatcher_api_surface_is_present(func):
    missing = MERCURE_API[func] - _params(func)
    assert not missing, f"vendored dicomweb_client no longer accepts {missing} for {func.__qualname__}"


def test_pillow_is_not_required_to_import_the_package():
    """Pillow must stay optional; only frame rendering needs it."""
    import dicomweb_client.file as file_module

    source = Path(file_module.__file__).read_text()
    assert "HAS_PIL" in source, "MERCURE.patch (optional Pillow) is missing from file.py"
    assert "except ImportError" in source.split("from PIL import Image")[-1][:200] or \
        "except ImportError" in source


def test_rendered_retrieval_fails_clearly_without_pillow(fs, monkeypatch):
    import dicomweb_client.file as file_module

    fs.create_dir("/vendored_dicoms")
    monkeypatch.setattr(file_module, "HAS_PIL", False)
    # in_memory=True is also mercure's fallback when the folder is not writable
    client = DICOMfileClient(url="file:///vendored_dicoms", in_memory=True, update_db=False)
    with pytest.raises(RuntimeError, match="Pillow"):
        client.retrieve_instance_frames("1.2.3", "1.2.4", "1.2.5", [1])
    with pytest.raises(RuntimeError, match="Pillow"):
        client.retrieve_instance_rendered("1.2.3", "1.2.4", "1.2.5")


def _instance(study: str, series: str) -> Dataset:
    ds = Dataset()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = study
    ds.SeriesInstanceUID = series
    ds.AccessionNumber = "VENDOR1"
    ds.PatientID = "MERCURE"
    ds.Modality = "OT"
    ds.StudyDate = "20260101"
    ds.Rows = ds.Columns = 8
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = bytes(64)
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    return ds


def test_file_target_round_trip(fs):
    """store / search / retrieve, i.e. what the dispatcher does with a file:// target."""
    fs.create_dir("/vendored_dicoms")
    study, series = generate_uid(), generate_uid()
    ds = _instance(study, series)
    client = DICOMfileClient(url="file:///vendored_dicoms", in_memory=True, update_db=True)

    response = client.store_instances([ds])
    assert len(getattr(response, "ReferencedSOPSequence", [])) == 1, "store failed: %s" % response
    assert not hasattr(response, "FailedSOPSequence")

    found = client.search_for_series(search_filters={"AccessionNumber": "VENDOR1"}, get_remaining=True)
    assert len(found) == 1
    assert isinstance(found[0], dict)  # the dispatcher feeds these to pydicom.Dataset.from_json

    stored = client.retrieve_series(study, series)
    assert [i.get("SOPInstanceUID") for i in stored] == [ds.SOPInstanceUID]


def test_require_pil_helper_exists():
    """Fails loudly if a refreshed vendored copy drops MERCURE.patch."""
    import importlib
    try:
        helper = getattr(importlib.import_module("dicomweb_client.file"), "_require_pil")
    except AttributeError:
        pytest.fail("dicomweb_client.file._require_pil missing: re-apply app/dicomweb_client/MERCURE.patch")
    assert callable(helper)
