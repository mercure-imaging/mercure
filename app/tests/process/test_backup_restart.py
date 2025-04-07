import json
import os
import shutil
import uuid
from pathlib import Path

import common.config as config
import pytest
from common.constants import mercure_names
from process.processor import backup_input_images

from app import common
from app.common.event_types import FailStage
from app.common.types import Module, Rule, Task, TaskInfo

logger = config.get_logger()

test_config = {
    "modules": {
        "test_module": Module(docker_tag="busybox:stable", settings={"fizz": "buzz"}).dict(),
    },
    "rules": {
        "test_rule": Rule(
            action="process",
            rule="True",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    }
}


def test_backup_input_images(fs, mercure_config):
    """Test that backup_input_images correctly copies files to as_received folder"""
    # Setup test environment
    processing_folder = Path(mercure_config(test_config).processing_folder)

    task_id = str(uuid.uuid1())
    task_folder = processing_folder / task_id

    fs.create_dir(task_folder)

    # Create test DICOM files and task.json
    fs.create_file(task_folder / "test1.dcm", contents="test dicom content 1")
    fs.create_file(task_folder / "test2.dcm", contents="test dicom content 2")
    fs.create_file(task_folder / mercure_names.TASKFILE, contents='{"id": "test-task"}')

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
    config = mercure_config(test_config)
    error_folder = Path(config.error_folder)
    processing_folder = Path(config.processing_folder)
    task_id = str(uuid.uuid1())
    task_folder = error_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)

    # Create test files in as_received folder
    fs.create_file(as_received_folder / "test1.dcm", contents="test dicom content 1")
    fs.create_file(as_received_folder / "test2.dcm", contents="test dicom content 2")
    fs.create_file(as_received_folder / mercure_names.TASKFILE,
                   contents=Task(
                       id=task_id,
                       info=TaskInfo(fail_stage='PROCESSING',
                                     action="process", mrn="1234", acc="asdf", mercure_version="idk",
                                     mercure_appliance="asdf", mercure_server="idk", uid=task_id, uid_type='series',
                                     triggered_rules='test_rule',
                                     applied_rule='test_rule'),
                   ).json())
    # Call the restart function via the API endpoint
    response = test_client.post(f"/queue/jobs/fail/restart-job",
                                headers={"Content-Type": "application/x-www-form-urlencoded"},
                                data=f"task_id={task_id}")

    # Check that the response is successful
    assert response.status_code == 200, f"Unexpected response code: {response.status_code} {response.text}"
    response_data = response.json()
    assert response_data.get("success") is True, f"Unexpected response data: {response_data} "

    # Check that in folder was created with copied files
    new_folder = processing_folder / task_id
    assert new_folder.exists(), f"{new_folder} does not exist"
    assert (new_folder / "test1.dcm").exists(), f"File 'test1.dcm' not found in {new_folder}"
    assert (new_folder / "test2.dcm").exists(), f"File 'test2.dcm' not found in {new_folder}"
    assert (new_folder / mercure_names.TASKFILE).exists(), f"File 'task.json' not found in {new_folder}"

    # Check that task.json was updated with reset status
    task_data = Task(**json.loads((new_folder / mercure_names.TASKFILE).read_text()))
    assert task_data, f"Task data is empty: {task_data}"
    assert task_data.process.module_name == "test_module", f"Module name is not 'test_module': {task_data}"

    # Check that monitor event was sent
    # assert common.monitor.send_task_event.called


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_id(test_client):
    """Test restart with missing task ID"""
    # Call the restart function via the API endpoint with no task_id
    response = test_client.post("/queue/jobs/fail/restart-job")

    # Check that the response contains an error
    assert response.status_code == 500, response.text
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "No task ID provided"


@pytest.mark.asyncio
async def test_restart_processing_job_no_task_folder(fs, mercure_config, test_client):
    """Test restart with non-existent task folder"""
    # Call the restart function via the API endpoint with a non-existent task_id
    task_id = str(uuid.uuid1())
    response = test_client.post(f"/queue/jobs/fail/restart-job",
                                headers={"Content-Type": "application/x-www-form-urlencoded"},
                                data=f"task_id={task_id}")

    # Check that the response contains an error
    assert response.status_code == 404, response.text
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "Task not found in error folder"


@pytest.mark.asyncio
async def test_restart_processing_job_no_as_received(fs, mercure_config, test_client):
    """Test restart with missing as_received folder"""
    # Setup test environment
    error_folder = Path(mercure_config(test_config).error_folder)
    task_id = str(uuid.uuid1())
    task_folder = error_folder / task_id
    fs.create_dir(task_folder)

    # Call the restart function via the API endpoint
    response = test_client.post(f"/queue/jobs/fail/restart-job",
                                headers={"Content-Type": "application/x-www-form-urlencoded"},
                                data=f"task_id={task_id}")
    # Check that the response contains an error
    assert response.status_code == 404
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "No original files found for this task"


@pytest.mark.asyncio
async def test_restart_processing_job_currently_processing(fs, mercure_config, test_client):
    """Test restart when task is currently being processed"""
    # Setup test environment
    config = mercure_config()
    error_folder = Path(config.error_folder)
    processing_folder = Path(config.processing_folder)
    task_id = str(uuid.uuid1())
    task_folder = error_folder / task_id
    as_received_folder = task_folder / "as_received"

    fs.create_dir(task_folder)
    fs.create_dir(as_received_folder)
    fs.create_file(as_received_folder / mercure_names.TASKFILE,
                   contents=Task(
                       id=task_id,
                       info=TaskInfo(fail_stage='PROCESSING',
                                     action="process", mrn="1234", acc="asdf", mercure_version="idk",
                                     mercure_appliance="asdf", mercure_server="idk", uid=task_id, uid_type='series',
                                     triggered_rules='test_rule',
                                     applied_rule='test_rule'),
                   ).json())

    fs.create_dir(processing_folder / task_id)

    # Call the restart function via the API endpoint
    response = test_client.post(f"/queue/jobs/fail/restart-job",
                                headers={"Content-Type": "application/x-www-form-urlencoded"},
                                data=f"task_id={task_id}")

    # Check that the response contains an error
    assert response.status_code == 200
    response_data = response.json()
    assert "error" in response_data
    assert response_data["error"] == "Task is currently being processed"
