import json
import os
import shutil
import uuid
from pathlib import Path

import common.config as config
import pytest
from common.constants import mercure_names
from process.processor import backup_input_images
from starlette.testclient import TestClient
from webinterface.queue import restart_processing_job

from app import common

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


@pytest.mark.asyncio
async def test_restart_processing_job_success(fs, mercure_config, test_client, mocked):
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

    # Call the restart function via the API endpoint
    response = test_client.get(f"/queue/jobs/processing/restart-job?task_id={task_id}")

    # Check that the response is successful
    assert response.status_code == 200, f"Unexpected response code: {response.status_code}"
    response_data = response.json()
    assert "success" in response_data and response_data["success"] is True, f"Unexpected response data: {response_data}"

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
    # assert common.monitor.send_task_event.called


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_id(test_client):
    """Test restart with missing task ID"""
    # Call the restart function via the API endpoint with no task_id
    response = test_client.get("/queue/jobs/processing/restart-job")

    # Check that the response contains an error
    assert response.status_code == 200
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "No task ID provided"


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_folder(fs, mercure_config, test_client):
    """Test restart with non-existent task folder"""
    # Call the restart function via the API endpoint with a non-existent task_id
    task_id = str(uuid.uuid1())
    response = test_client.get(f"/queue/jobs/processing/restart-job?task_id={task_id}")

    # Check that the response contains an error
    assert response.status_code == 200
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "Task folder not found"


@pytest.mark.asyncio
async def test_restart_processing_job_no_as_received(fs, mercure_config, test_client):
    """Test restart with missing as_received folder"""
    # Setup test environment
    processing_folder = Path(mercure_config().processing_folder)
    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    fs.create_dir(task_folder)

    # Call the restart function via the API endpoint
    response = test_client.get(f"/queue/jobs/processing/restart-job?task_id={task_id}")

    # Check that the response contains an error
    assert response.status_code == 200
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "No original files found for this task"


@pytest.mark.asyncio
async def test_restart_processing_job_currently_processing(fs, mercure_config, test_client):
    """Test restart when task is currently being processed"""
    # Setup test environment
    processing_folder = Path(mercure_config().processing_folder)
    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)

    # Create processing flag
    fs.create_file(task_folder / mercure_names.PROCESSING)

    # Call the restart function via the API endpoint
    response = test_client.get(f"/queue/jobs/processing/restart-job?task_id={task_id}")

    # Check that the response contains an error
    assert response.status_code == 200
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "Task is currently being processed"


@pytest.mark.asyncio
async def test_restart_processing_job_list_processing(fs, mercure_config, test_client, mocked):
    """Test restart with a list of processing modules"""
    # Setup test environment
    processing_folder = Path(mercure_config().processing_folder)
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

    # Call the restart function via the API endpoint
    response = test_client.get(f"/queue/jobs/processing/restart-job?task_id={task_id}")

    # Check that the response is successful
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["success"] is True

    # Check that in folder was created
    in_folder = task_folder / "in"
    assert in_folder.exists()
    assert (in_folder / mercure_names.TASKFILE).exists()

    # Check that task.json was updated with reset status for both modules
    task_data = json.loads((in_folder / mercure_names.TASKFILE).read_text())
    assert task_data["process"][0]["status"] == "pending"
    assert task_data["process"][1]["status"] == "pending"

    # Check that monitor event was sent
    # assert mocked.spy_called(common.monitor.send_task_event)
