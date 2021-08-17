"""
route_studies.py
================
Provides functions for routing and processing of studies (consisting of multiple series). 
"""

# Standard python includes
import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri
from datetime import datetime, timedelta


# App-specific includes
import common.config as config
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.notification as notification
import common.helper as helper
from common.types import EmptyDict, Task, TaskStudy
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
logger = daiquiri.getLogger("route_studies")


def route_studies() -> None:
    """
    Searches for completed studies and initiates the routing of the completed studies
    """
    studies_ready = {}

    with os.scandir(config.mercure[mercure_folders.STUDIES]) as it:
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
                monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message,
            )
        if not study_success:
            # TODO: Now move the study to the error folder
            pass

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
            task: Task = json.load(json_file)

        study = task.get("study", EmptyDict())
        # Check if processing of the study has been enforced (e.g., via UI selection)
        if study.get(mercure_study.COMPLETE_FORCE, "False") == "True":
            return True

        complete_trigger = study.get(mercure_study.COMPLETE_TRIGGER, "")
        if not complete_trigger:
            error_text = f"Missing trigger condition in task file in study folder {folder}"
            logger.error(error_text)
            monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
            return False

        complete_required_series = study.get(mercure_study.COMPLETE_REQUIRED_SERIES, "")

        # If trigger condition is received series but list of required series is missing, then switch to timeout mode instead
        if (complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES) and (
            not complete_required_series
        ):
            complete_trigger = mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT
            warning_text = f"Missing series for trigger condition in study folder {folder}. Using timeout instead"
            logger.warning(warning_text)
            monitor.send_event(
                monitor.m_events.PROCESSING, monitor.severity.WARNING, warning_text,
            )

        # Check for trigger condition
        if complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT:
            return check_study_timeout(task)
        elif complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES:
            return check_study_series(task, complete_required_series)
        else:
            error_text = f"Invalid trigger condition in task file in study folder {folder}"
            logger.error(error_text)
            monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
            return False

    except Exception:
        error_text = f"Invalid task file in study folder {folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False


def check_study_timeout(task: Task) -> bool:
    """
    Checks if the duration since the last series of the study was received exceeds the study completion timeout
    """
    last_received_string = task.get(mercure_sections.STUDY, {}).get(mercure_study.LAST_RECEIVE_TIME, "")
    if not last_received_string:
        return False

    last_received_time = datetime.strptime(last_received_string, "%Y-%m-%d %H:%M:%S")
    if datetime.now() > last_received_time + timedelta(seconds=config.mercure["study_forcecomplete_trigger"]):
        return True
    else:
        return False


def check_study_series(task: Task, required_series: str) -> bool:
    """
    Checks if all series required for study completion have been received
    """
    received_series = []

    # Fetch the list of received series descriptions from the task file
    if (mercure_study.RECEIVED_SERIES in task["study"]) and (isinstance(task["study"]["received_series"], list)):
        received_series = task["study"]["received_series"]

    # Check if the completion criteria is fulfilled
    return rule_evaluation.parse_completion_series(required_series, received_series)


def route_study(study) -> bool:
    """
    Processses the study in the folder 'study'. Loads the task file and delegates the action to helper functions
    """
    study_folder = config.mercure[mercure_folders.STUDIES] + "/" + study
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
        error_message = f"Unable to create study lock file {lock_file}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    try:
        # Read stored task file to determine completeness criteria
        with open(Path(study_folder) / mercure_names.TASKFILE, "r") as json_file:
            task: Task = json.load(json_file)
    except Exception:
        error_text = f"Invalid task file in study folder {study_folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        # TODO: Move study to error folder
        return False

    action_result = True
    action = task.get(mercure_sections.INFO, {}).get(mercure_info.ACTION, "")
    if not action:
        error_text = f"Missing action in study folder {study_folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        # TODO: Move study to error folder
        return False

    if action == mercure_actions.NOTIFICATION:
        action_result = push_studylevel_notification(study, task)
    elif action == mercure_actions.ROUTE:
        action_result = push_studylevel_dispatch(study, task)
    elif action == mercure_actions.PROCESS or action == mercure_actions.BOTH:
        action_result = push_studylevel_processing(study, task)
    else:
        # This point should not be reached (discard actions should be handled on the series level)
        error_text = f"Invalid task action in study folder {study_folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    # TODO: Try moving the study folder to the error folder if the action was not successful

    if not remove_study_folder(study, lock):
        error_text = f"Error removing folder for study {study}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    return True


def push_studylevel_dispatch(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the dispatchter, including the generated task file containing the destination information
    """
    return move_study_folder(study, "OUTGOING")


def push_studylevel_processing(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the processor, including the generated task file containing the processing instructions
    """
    return move_study_folder(study, "PROCESSING")


def push_studylevel_notification(study: str, task: Task) -> bool:
    """
    Executes the study-level reception notification
    """
    # Check if the applied_rule is available
    current_rule = task["info"].get("applied_rule", "")
    if not current_rule:
        error_text = f"Missing applied_rule in task file in study {study}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    # Check if the mercure configuration still contains that rule
    if not isinstance(config.mercure[mercure_config.RULES].get(current_rule, ""), dict):
        error_text = f"Applied rule not existing anymore in mercure configuration {study}"
        logger.exception(error_text)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    # OK, now fire out the webhook
    notification.send_webhook(
        config.mercure[mercure_config.RULES][current_rule].get(mercure_rule.NOTIFICATION_WEBHOOK, ""),
        config.mercure[mercure_config.RULES][current_rule].get(mercure_rule.NOTIFICATION_PAYLOAD, ""),
        mercure_events.RECEPTION,
    )

    move_study_folder(study, "SUCCESS")
    return True


def move_study_folder(study: str, destination: str) -> bool:
    """
    Moves the study subfolder to the specified destination with proper locking of the folders
    """
    source_folder = config.mercure[mercure_folders.STUDIES] + "/" + study
    destination_folder = config.mercure[mercure_folders.DISCARD]
    if destination == "PROCESSING":
        destination_folder = config.mercure[mercure_folders.PROCESSING]

    # Create unique name of destination folder
    destination_folder += "/" + str(uuid.uuid1())

    # Create the destination folder and validate that is has been created
    try:
        os.mkdir(destination_folder)
    except Exception:
        error_message = f"Unable to create study destination folder {destination_folder}"
        logger.exception(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    if not Path(destination_folder).exists():
        error_message = f"Creating study destination folder not possible {destination_folder}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    # Create lock file in destination folder (to prevent any other module to work on the folder). Note that
    # the source folder has already been locked in the parent function.
    lock_file = Path(destination_folder) / mercure_names.LOCK
    try:
        lock = helper.FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        error_message = f"Unable to create lock file {destination_folder}/{mercure_names.LOCK}"
        logger.error(error_message)
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message,
        )
        return False

    # Move all files except the lock file
    for entry in os.scandir(source_folder):
        if not entry.name.endswith(mercure_names.LOCK):
            try:
                shutil.move(source_folder + "/" + entry.name, destination_folder + "/" + entry.name)
            except Exception:
                error_message = f"Problem while pushing file {entry} from {source_folder} to {destination_folder}"
                logger.exception(error_message)
                monitor.send_event(
                    monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message,
                )

    # Remove the lock file. Would happen automatically when leaving the function, but better to do
    # explicitly to provide error handling
    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        error_message = f"Unable to remove lock file {lock_file}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    return True


def remove_study_folder(study: str, lock: helper.FileLock) -> bool:
    """
    Removes a study folder containing nothing but the lock file (called during cleanup after all files have 
    been moved somewhere else already)
    """
    study_folder = config.mercure[mercure_folders.STUDIES] + "/" + study
    # Remove the lock file
    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        error_message = f"Unable to remove lock file while removing study folder {study}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False
    # Remove the empty study folder
    try:
        shutil.rmtree(study_folder)
    except Exception as e:
        error_message = f"Unable to delete folder {study_folder}"
        logger.error(error_message)
        logger.exception(e)
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Unable to delete study folder {study_folder}",
        )
    return True
