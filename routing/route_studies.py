import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri

# App-specific includes
import common.config as config
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.helper as helper
from common.constants import (
    mercure_defs,
    mercure_names,
    mercure_actions,
    mercure_rule,
    mercure_config,
    mercure_options,
    mercure_folders,
    mercure_sections,
)


logger = daiquiri.getLogger("route_studies")


def is_study_locked(folder):
    path = Path(folder)
    folder_status = (path / mercure_names.LOCK).exists() or (path / mercure_names.PROCESSING).exists() or len(list(path.glob(mercure_names.DCMFILTER))) == 0
    return folder_status


def is_study_complete(folder):
    try:
        # Read stored task file to determine completeness criteria
        with open(Path(folder) / mercure_names.TASKFILE, "r") as json_file:
            task = json.load(json_file)

        complete_trigger = task.get(mercure_sections.STUDY, {}).get("complete_trigger", "")
        if not complete_trigger:
            error_text = f"Missing trigger condition in task file in study folder {folder}"
            logger.error(error_text)
            monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_text)
            return False

        complete_required_series = task.get(mercure_sections.STUDY, {}).get("complete_required_series", "")

        # If trigger condition is received series but list of required series is missing, then switch to timeout mode instead
        if (complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES) and (not complete_required_series):
            complete_trigger = mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT
            warning_text = f"Missing series for trigger condition in study folder {folder}. Using timeout instead"
            logger.warning(warning_text)
            monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.WARNING, warning_text)

        # Check for trigger condition
        if complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_TIMEOUT:
            return check_study_timeout(task)
        elif complete_trigger == mercure_rule.STUDY_TRIGGER_CONDITION_RECEIVED_SERIES:
            return check_study_timeout(task)
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


def check_study_timeout(task):
    # TODO
    return False


def check_study_series(task):
    # TODO
    return False


def route_studies():
    studies_ready = {}

    with os.scandir(config.mercure[mercure_folders.STUDIES]) as it:
        for entry in it:
            if entry.is_dir() and not is_study_locked(entry.path) and is_study_complete(entry.path):
                modificationTime = entry.stat().st_mtime
                studies_ready[entry.name] = modificationTime

    # Process all complete studies
    for entry in sorted(studies_ready):
        try:
            route_study(entry)
        except Exception:
            logger.exception(f"Problems while processing study {entry}")
            # TODO: Add study events to bookkeeper
            # monitor.send_series_event(monitor.s_events.ERROR, entry, 0, "", "Exception while processing")
            monitor.send_event(
                monitor.h_events.PROCESSING,
                monitor.severity.ERROR,
                f"Exception while processing study {entry}",
            )

        # If termination is requested, stop processing after the active study has been completed
        if helper.is_terminated():
            return


def route_study(study):
    # TODO
    pass
