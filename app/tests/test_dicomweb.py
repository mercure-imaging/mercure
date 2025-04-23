"""
test_dicomweb.py
===============
Test the DICOMweb interface functionality.
"""

import io
import json
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pydicom
import pytest
import webgui
from common.types import Rule
from requests_toolbelt.multipart.encoder import MultipartEncoder
from starlette.testclient import TestClient
from tests.testing_common import create_minimal_dicom

rules = {
    "rules": {
        "test_rule": Rule(
            rule="False", action="route", action_trigger="series"
        ).dict(),
    }
}

# Can't fix this from outside starlette.testclient
pytestmark = pytest.mark.filterwarnings("ignore:Use 'content=<...>' to upload raw bytes/text content")


def multipart_upload(test_client: TestClient, fields) -> Any:

    m = MultipartEncoder(
        fields=fields,
        boundary=uuid.uuid4()
    )

    # Send request
    return test_client.post(
        "/tools/upload/store",
        headers={
            "Content-Type": f"multipart/related; boundary={m.boundary_value}",
        },
        data=m.to_string()
    )


def create_test_dicom(output_filename) -> pydicom.Dataset:
    """Create a test DICOM file."""
    series_uid = "1.2.3.4"
    tags = {
        "PatientName": "Test^Patient",
        "PatientID": "123456",
        "AccessionNumber": "ACC12345",
        "StudyDescription": "Test Study"
    }
    ds = create_minimal_dicom(output_filename, series_uid, tags)
    return ds


def create_test_zip(path, num_files=3) -> bytes:
    """Create a test ZIP file with DICOM files."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        for i in range(num_files):
            # Create a temporary DICOM file
            temp_file = f"{path}/temp_{i}.dcm"
            create_test_dicom(temp_file)

            # Add it to the ZIP
            zip_file.write(temp_file, f"file_{i}.dcm")

            # Clean up
            os.unlink(temp_file)

    zip_buffer.seek(0)
    return zip_buffer.read()


def test_dicomweb_index(test_client):
    """Test the root endpoint of the DICOMweb API."""
    response = test_client.get("/api")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# def test_upload_page_requires_auth(test_client):
#     """Test that the upload page requires authentication."""
#     response = test_client.get("/tools/upload", follow_redirects=False)
#     # Should redirect to login
#     assert response.status_code == 303
#     assert response.headers["location"].startswith("http://testserver/login?")


def test_stow_rs_with_dicom_part(test_client: TestClient, fs, mercure_config):
    """Test uploading DICOM files via STOW-RS with multipart data."""

    # Create test DICOM file
    config = mercure_config(rules)
    dcm_path = "/tmp/test/test.dcm"
    create_test_dicom(dcm_path)

    with open(dcm_path, 'rb') as f:
        dcm_content = f.read()
    # Create multipart body

    response = multipart_upload(
        test_client,
        {
            'dicom_file': ('test.dcm', dcm_content, 'application/dicom'),
            'form_data': ('', 'force_rule=test_rule', 'application/x-www-form-urlencoded')
        }
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["file_count"] == 1
    out_tags = config.incoming_folder+"/1.2.3.4/1.2.3.4#dicom_0.tags"
    assert os.path.exists(out_tags)
    assert json.load(open(out_tags))["mercureForceRule"] == "test_rule"


def test_stow_rs_with_zip_part(test_client: TestClient, fs, mercure_config):
    """Test uploading a zip file with DICOM files via STOW-RS."""
    config = mercure_config(rules)

    # Create test ZIP file
    zip_content = create_test_zip("/tmp/test.zip", num_files=3)

    response = multipart_upload(
        test_client, {
            'zip_file': ('test.zip', zip_content, 'application/zip'),
            'form_data': ('', 'save_dataset=true&dataset_name=test_zip_dataset', 'application/x-www-form-urlencoded')
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["file_count"] == 3  # We created 3 DICOM files in the ZIP

    for k in range(3):
        out_tags = config.incoming_folder+f"/1.2.3.4/1.2.3.4#file_{k}.tags"
    assert os.path.exists(out_tags)


def test_dataset_operations(test_client: TestClient, fs, mercure_config):
    """Test operations on datasets."""

    config = mercure_config(rules)
    dataset_path = Path(config.jobs_folder) / "uploaded_datasets" / "admin" / "test_dataset"
    dataset_path.mkdir(exist_ok=True, parents=True)
    # Create a test DICOM file in the series folder
    dcm_path = dataset_path / "dicom_0.dcm"
    create_test_dicom(dcm_path)

    # Test GET operation
    response = test_client.get("/tools/dataset/test_dataset")
    assert response.status_code == 200, f"Response: {response.json()}"
    assert response.json()["id"] == "test_dataset"
    # assert "series_1" in response.json()["series_count"]

    # Test POST operation (resubmit)
    response = test_client.post("/tools/dataset/test_dataset")
    assert response.status_code == 200, f"Response: {response.json()}"
    assert response.json()["status"] == "success", f"Response: {response.json()}"

    out_tags = config.incoming_folder+"/1.2.3.4/1.2.3.4#dicom_0.tags"
    assert "mercureForceRule" not in json.load(open(out_tags))

    shutil.rmtree(config.incoming_folder+"/1.2.3.4")

    response = test_client.post("/tools/dataset/test_dataset", data={"force_rule": "test_rule"})
    assert response.status_code == 200, f"Response: {response.json()}"
    assert response.json()["status"] == "success", f"Response: {response.json()}"
    assert json.load(open(out_tags))["mercureForceRule"] == "test_rule"

    response = test_client.post("/tools/dataset/test_dataset", data={"force_rule": "nonexistent_rule"})
    assert response.status_code == 404, f"Response: {response.json()}"

    # Test DELETE operation
    response = test_client.delete("/tools/dataset/test_dataset")
    assert response.status_code == 200, f"Response: {response.json()}"
    assert response.json()["status"] == "success", f"Response: {response.json()}"
    assert not dataset_path.exists()


def test_invalid_dataset_operations(test_client):
    """Test operations on invalid datasets."""

    # Test non-existent dataset
    response = test_client.post("/tools/dataset/non_existent")
    assert response.status_code == 404

    response = test_client.get("/tools/dataset/non_existent")
    assert response.status_code == 404

    response = test_client.delete("/tools/dataset/non_existent")
    assert response.status_code == 404


def test_stow_rs_error_handling(test_client):
    """Test error handling in the STOW-RS endpoint."""

    # Test invalid content type
    response = test_client.post(
        "/tools/upload/store",
        headers={
            "Content-Type": "application/json",
        },
        json={"test": "data"}
    )
    assert response.status_code == 500

    # Test missing boundary
    response = test_client.post(
        "/tools/upload/store",
        headers={
            "Content-Type": "multipart/related",
        },
        data="test data"
    )
    assert response.status_code == 500

    # Test no DICOM instances
    response = multipart_upload(
        test_client,
        {
            'form_data': ('', 'force_rule=test_rule', 'application/x-www-form-urlencoded')
        }
    )

    assert response.status_code == 400
    assert "No DICOM instances found" in response.json().get("error", "")

    # Create test DICOM file
    dcm_path = "/tmp/test.dcm"
    create_test_dicom(dcm_path)

    with open(dcm_path, 'rb') as f:
        dcm_content = f.read()

    response = multipart_upload(
        test_client,
        {
            'dicom_file': ('test.dcm', dcm_content, 'application/dicom'),
            'form_data': ('', 'save_dataset=true', 'application/x-www-form-urlencoded')
        }
    )
    assert response.status_code == 500
    assert "dataset name is required" in response.json().get("error", "").lower()


if __name__ == "__main__":
    pytest.main(["-xvs", "test_dicomweb.py"])
