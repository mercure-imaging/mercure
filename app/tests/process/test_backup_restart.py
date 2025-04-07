import json
import os
import shutil
import uuid
from pathlib import Path

import common.config as config
import pytest
from common.constants import mercure_names
from process.processor import backup_input_images
from pytest_mock import MockerFixture
from webinterface.queue import restart_processing_job

logger = config.get_logger()


def test_backup_input_images(fs, mercure_config):
    """Test that backup_input_images correctly copies files to as_received folder"""
    # Setup test environment
    processing_folder = Path(mercure_config().processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    in_folder = task_folder / "in"

    fs.create_dir(task_folder)
    fs.create_dir(in_folder)

    # Create test DICOM files and task.json
    fs.create_file(in_folder / "test1.dcm", contents="test dicom content 1")
    fs.create_file(in_folder / "test2.dcm", contents="test dicom content 2")
    fs.create_file(in_folder / mercure_names.TASKFILE, contents='{"id": "test-task"}')

    # Run the backup function
    backup_input_images(task_folder)

    # Check that as_received folder was created
    backup_folder = task_folder / "as_received"
    assert backup_folder.exists()

    # Check that files were copied correctly
    assert (backup_folder / "test1.dcm").exists()
    assert (backup_folder / "test2.dcm").exists()
    assert (backup_folder / "task.json").exists()

    # Check file contents
    assert (backup_folder / "test1.dcm").read_text() == "test dicom content 1"
    assert (backup_folder / "test2.dcm").read_text() == "test dicom content 2"
    assert (backup_folder / "task.json").read_text() == '{"id": "test-task"}'


class MockRequest:
    def __init__(self, query_params=None):
        self.query_params = query_params or {}


@pytest.mark.asyncio
async def test_restart_processing_job_success(fs, mercure_config):
    """Test successful restart of a processing job"""
    # Setup test environment
    processing_folder = Path(mercure_config().processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)

    # Create test files in as_received folder
    fs.create_file(as_received_folder / "test1.dcm", contents="test dicom content 1")
    fs.create_file(as_received_folder / "test2.dcm", contents="test dicom content 2")
    fs.create_file(as_received_folder / mercure_names.TASKFILE,
                   contents='{"id": "test-task", "process": {"module_name": "test_module", "status": "completed"}}')

    # Create a mock request with task_id
    request = MockRequest(query_params={"task_id": task_id})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned success
    assert response_data["success"] is True

    # Check that in folder was created with copied files
    in_folder = task_folder / "in"
    assert in_folder.exists()
    assert (in_folder / "test1.dcm").exists()
    assert (in_folder / "test2.dcm").exists()
    assert (in_folder / mercure_names.TASKFILE).exists()

    # Check that task.json was updated with reset status
    task_data = json.loads((in_folder / mercure_names.TASKFILE).read_text())
    assert task_data["process"]["status"] == "pending"

    # Check that monitor event was sent
    mock_send_event.assert_called_once()


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_id(fs, monkeypatch):
    """Test restart with missing task ID"""
    # Mock the config.mercure.processing_folder
    processing_folder = Path("/var/processing")
    monkeypatch.setattr("common.config.mercure.processing_folder", str(processing_folder))

    # Create a mock request with no task_id
    request = MockRequest(query_params={})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned error
    assert "error" in response_data
    assert response_data["error"] == "No task ID provided"


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_folder(fs, monkeypatch):
    """Test restart with non-existent task folder"""
    # Mock the config.mercure.processing_folder
    processing_folder = Path("/var/processing")
    fs.create_dir(processing_folder)
    monkeypatch.setattr("common.config.mercure.processing_folder", str(processing_folder))

    # Create a mock request with task_id that doesn't exist
    task_id = str(uuid.uuid1())
    request = MockRequest(query_params={"task_id": task_id})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned error
    assert "error" in response_data
    assert response_data["error"] == "Task folder not found"


@pytest.mark.asyncio
async def test_restart_processing_job_no_as_received(fs, monkeypatch):
    """Test restart with missing as_received folder"""
    # Setup test environment
    processing_folder = Path("/var/processing")
    fs.create_dir(processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id

    fs.create_dir(task_folder)

    # Mock the config.mercure.processing_folder
    monkeypatch.setattr("common.config.mercure.processing_folder", str(processing_folder))

    # Create a mock request with task_id
    request = MockRequest(query_params={"task_id": task_id})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned error
    assert "error" in response_data
    assert response_data["error"] == "No original files found for this task"


@pytest.mark.asyncio
async def test_restart_processing_job_currently_processing(fs, monkeypatch):
    """Test restart when task is currently being processed"""
    # Setup test environment
    processing_folder = Path("/var/processing")
    fs.create_dir(processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)

    # Create processing flag
    fs.create_file(task_folder / mercure_names.PROCESSING)

    # Mock the config.mercure.processing_folder
    monkeypatch.setattr("common.config.mercure.processing_folder", str(processing_folder))

    # Create a mock request with task_id
    request = MockRequest(query_params={"task_id": task_id})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned error
    assert "error" in response_data
    assert response_data["error"] == "Task is currently being processed"


@pytest.mark.asyncio
async def test_restart_processing_job_list_processing(fs, monkeypatch):
    """Test restart with a list of processing modules"""
    # Setup test environment
    processing_folder = Path("/var/processing")
    fs.create_dir(processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)

    # Create test files in as_received folder
    process_list = [
        {"module_name": "module1", "status": "completed"},
        {"module_name": "module2", "status": "error"}
    ]
    task_json = {"id": "test-task", "process": process_list}
    fs.create_file(as_received_folder / mercure_names.TASKFILE, contents=json.dumps(task_json))

    # Mock the monitor.send_task_event function
    mock_send_event = pytest.mock.MagicMock()
    monkeypatch.setattr("common.monitor.send_task_event", mock_send_event)

    # Mock the config.mercure.processing_folder
    monkeypatch.setattr("common.config.mercure.processing_folder", str(processing_folder))

    # Create a mock request with task_id
    request = MockRequest(query_params={"task_id": task_id})

    # Call the restart function
    response = await restart_processing_job(request)
    response_data = json.loads(response.body)

    # Check that the function returned success
    assert response_data["success"] is True

    # Check that in folder was created
    in_folder = task_folder / "in"
    assert in_folder.exists()
    assert (in_folder / mercure_names.TASKFILE).exists()

    # Check that task.json was updated with reset status for both modules
    task_data = json.loads((in_folder / mercure_names.TASKFILE).read_text())
    assert task_data["process"][0]["status"] == "pending"
    assert task_data["process"][1]["status"] == "pending"
