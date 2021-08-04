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
        try:
            route_study(dir_entry)
        except Exception:
            error_message = f"Problems while processing study {dir_entry}"
            logger.exception(error_message)
            # TODO: Add study events to bookkeeper
            # monitor.send_series_event(monitor.s_events.ERROR, entry, 0, "", "Exception while processing")
            monitor.send_event(
                monitor.h_events.PROCESSING, monitor.severity.ERROR, error_message,
            )

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
            monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
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
                monitor.h_events.PROCESSING, monitor.severity.WARNING, warning_text,
            )

        # Check for trigger condition
        if complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT:
            return check_study_timeout(task)
        elif complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES:
            return check_study_series(task, complete_required_series)
        else:
            error_text = f"Invalid trigger condition in task file in study folder {folder}"
            logger.error(error_text)
            monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
            return False

    except Exception:
        error_text = f"Invalid task file in study folder {folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

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

    # TODO: Lock study folder

    try:
        # Read stored task file to determine completeness criteria
        with open(Path(study_folder) / mercure_names.TASKFILE, "r") as json_file:
            task: Task = json.load(json_file)

    except Exception:
        error_text = f"Invalid task file in study folder {study_folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    action = task.get(mercure_sections.INFO, {}).get(mercure_info.ACTION, "")
    if not action:
        error_text = f"Missing action in study folder {study_folder}"
        logger.exception(error_text)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
        return False

    if action == mercure_actions.NOTIFICATION:
        return push_studylevel_notification(study, task)

    if action == mercure_actions.ROUTE:
        return push_studylevel_dispatch(study, task)

    if action == mercure_actions.PROCESS or action == mercure_actions.BOTH:
        return push_studylevel_processing(study, task)

    # This point should not be reached (discard actions should be handled on the series level)
    error_text = f"Invalid task action in study folder {study_folder}"
    logger.exception(error_text)
    monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
    return False


def push_studylevel_dispatch(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the dispatchter, including the generated task file containing the destination information
    """
    # TODO
    return True


def push_studylevel_processing(study: str, task: Task) -> bool:
    """
    Pushes the study folder to the processor, including the generated task file containing the processing instructions
    """
    # TODO
    return True


def push_studylevel_notification(study: str, task: Task) -> bool:
    """
    Executes the study-level reception notification
    """
    # TODO
    return True
