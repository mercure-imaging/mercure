"""
route_studies.py
================
Provides functions for routing and processing of studies (consisting of multiple series). 
"""

# Standard python includes
import os
from pathlib import Path
from typing import Optional, Union
import uuid
import json
import shutil
import daiquiri
from datetime import datetime, timedelta

# App-specific includes
import common.config as config
from common.exceptions import handle_error
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.notification as notification
import common.helper as helper
from common.types import Rule, Task, TaskHasStudy, TaskInfo
from common.constants import (
    mercure_defs,
    mercure_names,
    mercure_actions,
    mercure_rule,
    mercure_config,
    mercure_options,
    mercure_folders,
    mercure_sections,
    mercure_study,
    mercure_info,
    mercure_events,
)


# Create local logger instance
logger = config.get_logger()


def route_studies() -> None:
    """
    Searches for completed studies and initiates the routing of the completed studies
    """
    # TODO: Handle studies that exceed the "force completion" timeout in the "CONDITION_RECEIVED_SERIES" mode
    studies_ready = {}
    with os.scandir(config.mercure.studies_folder) as it:
        for entry in it:
            if entry.is_dir() and not is_study_locked(entry.path) and is_study_complete(entry.path):
                modificationTime = entry.stat().st_mtime
                studies_ready[entry.name] = modificationTime

    # Process all complete studies
    for dir_entry in sorted(studies_ready):
        study_success = False
        try:
            study_success = route_study(dir_entry)
        except Exception:
            error_message = f"Problems while processing study {dir_entry}"
            logger.exception(error_message)
            # TODO: Add study events to bookkeeper
            # monitor.send_series_event(monitor.s_events.ERROR, entry, 0, "", "Exception while processing")
            monitor.send_event(
                monitor.m_events.PROCESSING,
                monitor.severity.ERROR,
                error_message,
            )
        if not study_success:
            # Move the study to the error folder to avoid repeated processing
            push_studylevel_error(dir_entry)

        # If termination is requested, stop processing after the active study has been completed
        if helper.is_terminated():
            return


def is_study_locked(folder: str) -> bool:
    """
    Returns true if the given folder is locked, i.e. if another process is already working on the study
    """
    path = Path(folder)
    folder_status = (
        (path / mercure_names.LOCK).exists()
        or (path / mercure_names.PROCESSING).exists()
        or len(list(path.glob(mercure_names.DCMFILTER))) == 0
    )
    return folder_status


def is_study_complete(folder: str) -> bool:
    """
    Returns true if the study in the given folder is ready for processing, i.e. if the completeness criteria of the triggered rule has been met
    """
    try:
        # Read stored task file to determine completeness criteria
        with open(Path(folder) / mercure_names.TASKFILE, "r") as json_file:
            task: TaskHasStudy = TaskHasStudy(**json.load(json_file))

        study = task.study

        # Check if processing of the study has been enforced (e.g., via UI selection)
        if study.get("complete_force", "False") == "True":
            return True

        complete_trigger = study.complete_trigger

        if not complete_trigger:
            handle_error(f"Missing trigger condition in task file in study folder {folder}", task.id)
            return False

        complete_required_series = study.get("complete_required_series", "")

        # If trigger condition is received series but list of required series is missing, then switch to timeout mode instead
        if (complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES) and (
            not complete_required_series
        ):
            complete_trigger = mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT
            handle_error(
                f"Missing series for trigger condition in study folder {folder}. Using timeout instead",
                task.id,
                severity=monitor.severity.WARNING,
            )

        # Check for trigger condition
        if complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT:
            return check_study_timeout(task)
        elif complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES:
            return check_study_series(task, complete_required_series)
        else:
            handle_error(f"Invalid trigger condition in task file in study folder {folder}", task.id)
            return False

    except Exception:
        handle_error(f"Invalid task file in study folder {folder}", task.id)
        return False


def check_study_timeout(task: TaskHasStudy) -> bool:
    """
    Checks if the duration since the last series of the study was received exceeds the study completion timeout
    """
    study = task.study
    last_received_string = study.last_receive_time
    if not last_received_string:
        return False

    last_receive_time = datetime.strptime(last_received_string, "%Y-%m-%d %H:%M:%S")
    if datetime.now() > last_receive_time + timedelta(seconds=config.mercure.study_complete_trigger):
        return True
    else:
        return False


def check_study_series(task: TaskHasStudy, required_series: str) -> bool:
    """
    Checks if all series required for study completion have been received
    """
    received_series = []

    # Fetch the list of received series descriptions from the task file
    if (task.study.received_series) and (isinstance(task.study.received_series, list)):
        received_series = task.study.received_series

    # Check if the completion criteria is fulfilled
    return rule_evaluation.parse_completion_series(task.id, required_series, received_series)


def route_study(study) -> bool:
    """
    Processses the study in the folder 'study'. Loads the task file and delegates the action to helper functions
    """
    study_folder = config.mercure.studies_folder + "/" + study
    if is_study_locked(study_folder):
        # If the study folder has been locked in the meantime, then skip and proceed with the next one
        return True

    # Create lock file in the study folder and prevent other instances from working on this study
    lock_file = Path(study_folder + "/" + study + mercure_names.LOCK)
    if lock_file.exists():
        return True
    try:
        lock = helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        try:
            with open(Path(study_folder) / mercure_names.TASKFILE, "r") as json_file:
                task: Task = Task(**json.load(json_file))
            handle_error(f"Unable to create study lock file {lock_file}", task.id)
        except:
            handle_error(f"Unable to create study lock file {lock_file}", None)
        return False

    try:
        # Read stored task file to determine completeness criteria
        with open(Path(study_folder) / mercure_names.TASKFILE, "r") as json_file:
            task = Task(**json.load(json_file))
    except Exception:
        try:
            with open(Path(study_folder) / mercure_names.TASKFILE, "r") as json_file:
                handle_error(f"Invalid task file in study folder {study_folder}", json.load(json_file)["id"])
        except:
            handle_error(f"Invalid task file in study folder {study_folder}", None)
        return False

    action_result = True
    info: TaskInfo = task.info
    action = info.get("action", "")

    if not action:
        handle_error(f"Missing action in study folder {study_folder}", task.id)
        return False

    # TODO: Clean folder for duplicate DICOMs (i.e., if series have been sent twice -- check by instance UID)

    if action == mercure_actions.NOTIFICATION:
        action_result = push_studylevel_notification(study, task)
    elif action == mercure_actions.ROUTE:
        action_result = push_studylevel_dispatch(study, task)
    elif action == mercure_actions.PROCESS or action == mercure_actions.BOTH:
        action_result = push_studylevel_processing(study, task)
    else:
        # This point should not be reached (discard actions should be handled on the series level)
        handle_error(f"Invalid task action in study folder {study_folder}", task.id)
        return False

    if not action_result:
        handle_error(f"Error during processing of study {study}", task.id)
        return False

    if not remove_study_folder(task.id, study, lock):
        handle_error(f"Error removing folder of study {study}", task.id)
        return False

    return True


def push_studylevel_dispatch(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the dispatchter, including the generated task file containing the destination information
    """
    trigger_studylevel_notification(study, task, mercure_events.RECEPTION)
    return move_study_folder(task.id, study, "OUTGOING")


def push_studylevel_processing(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the processor, including the generated task file containing the processing instructions
    """
    trigger_studylevel_notification(study, task, mercure_events.RECEPTION)
    return move_study_folder(task.id, study, "PROCESSING")


def push_studylevel_notification(study: str, task: Task) -> bool:
    """
    Executes the study-level reception notification
    """
    trigger_studylevel_notification(study, task, mercure_events.RECEPTION)
    trigger_studylevel_notification(study, task, mercure_events.COMPLETION)
    move_study_folder(task.id, study, "SUCCESS")
    return True


def push_studylevel_error(study: str) -> None:
    """
    Pushes the study folder to the error folder after unsuccessful processing
    """
    study_folder = config.mercure.studies_folder + "/" + study
    lock_file = Path(study_folder + "/" + study + mercure_names.LOCK)
    if lock_file.exists():
        # Study normally shouldn't be locked at this point, but since it is, just exit and wait.
        # Might require manual intervention if a former process terminated without removing the lock file
        return
    try:
        lock = helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        handle_error(f"Unable to lock study for removal {lock_file}")
        return
    if not move_study_folder(None, study, "ERROR"):
        # At this point, we can only wait for manual intervention
        handle_error(f"Unable to move study to ERROR folder {lock_file}")
        return
    if not remove_study_folder(None, study, lock):
        handle_error(f"Unable to delete study folder {lock_file}")
        return


def move_study_folder(task_id: Union[str, None], study: str, destination: str) -> bool:
    """
    Moves the study subfolder to the specified destination with proper locking of the folders
    """
    source_folder = config.mercure.studies_folder + "/" + study
    destination_folder = config.mercure.discard_folder
    if destination == "PROCESSING":
        destination_folder = config.mercure.processing_folder
    elif destination == "SUCCESS":
        destination_folder = config.mercure.success_folder
    elif destination == "ERROR":
        destination_folder = config.mercure.error_folder
    elif destination == "OUTGOING":
        destination_folder = config.mercure.outgoing_folder
    else:
        handle_error(f"Unknown destination {destination} requested for {study}", task_id)
        return False

    # Create unique name of destination folder
    destination_folder += "/" + str(uuid.uuid1())

    # Create the destination folder and validate that is has been created
    try:
        os.mkdir(destination_folder)
    except Exception:
        handle_error(f"Unable to create study destination folder {destination_folder}", task_id)
        return False

    if not Path(destination_folder).exists():
        handle_error(f"Creating study destination folder not possible {destination_folder}", task_id)
        return False

    # Create lock file in destination folder (to prevent any other module to work on the folder). Note that
    # the source folder has already been locked in the parent function.
    lock_file = Path(destination_folder) / mercure_names.LOCK
    try:
        lock = helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        handle_error(f"Unable to create lock file {destination_folder}/{mercure_names.LOCK}", task_id)
        return False

    # Move all files except the lock file
    # FIXME: if we don't use a list instead of an iterator, in testing we get an error from pyfakefs about the iterator changing during the iteration
    for entry in list(os.scandir(source_folder)):
        # Move all files but exclude the lock file in the source folder
        if not entry.name.endswith(mercure_names.LOCK):
            try:
                shutil.move(source_folder + "/" + entry.name, destination_folder + "/" + entry.name)
            except Exception:
                handle_error(
                    f"Problem while pushing file {entry} from {source_folder} to {destination_folder}", task_id
                )

    # Remove the lock file in the target folder. Would happen automatically when leaving the function,
    # but better to do explicitly with error handling
    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        handle_error(f"Unable to remove lock file {lock_file}", task_id)
        return False

    return True


def remove_study_folder(task_id: Union[str, None], study: str, lock: helper.FileLock) -> bool:
    """
    Removes a study folder containing nothing but the lock file (called during cleanup after all files have
    been moved somewhere else already)
    """
    study_folder = config.mercure.studies_folder + "/" + study
    # Remove the lock file
    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        handle_error(f"Unable to remove lock file while removing study folder {study}", task_id)
        return False
    # Remove the empty study folder
    try:
        shutil.rmtree(study_folder)
    except Exception as e:
        handle_error(f"Unable to delete study folder {study_folder}", task_id)
    return True


def trigger_studylevel_notification(study: str, task: Task, event) -> bool:
    # Check if the applied_rule is available
    current_rule = task.info.applied_rule
    if not current_rule:
        handle_error(f"Missing applied_rule in task file in study {study}", task.id)
        return False

    # Check if the mercure configuration still contains that rule
    if not isinstance(config.mercure.rules.get(current_rule, ""), Rule):
        handle_error(f"Applied rule not existing anymore in mercure configuration {study}", task.id)
        return False

    # OK, now fire out the webhook if configured
    if event == mercure_events.RECEPTION:
        if config.mercure.rules[current_rule].notification_trigger_reception == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.RECEPTION,
                current_rule,
            )
    if event == mercure_events.COMPLETION:
        if config.mercure.rules[current_rule].notification_trigger_completion == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.COMPLETION,
                current_rule,
            )
    if event == mercure_events.ERROR:
        if config.mercure.rules[current_rule].notification_trigger_error == "True":
            notification.send_webhook(
                config.mercure.rules[current_rule].get("notification_webhook", ""),
                config.mercure.rules[current_rule].get("notification_payload", ""),
                mercure_events.ERROR,
                current_rule,
            )

    return True
