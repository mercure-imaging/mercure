"""
generate_taskfile.py
====================
Helper functions for generating task files in json format, which describe the job to be done and maintain a journal of the executed actions.
"""

# Standard python includes
import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri
import socket
from datetime import datetime
from mypy_extensions import TypedDict
from typing_extensions import Literal
from typing import Dict, Optional, Union, List, cast

# App-specific includes
import common.config as config
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.helper as helper
from common.types import *
from common.constants import (
    mercure_defs,
    mercure_names,
    mercure_sections,
    mercure_rule,
    mercure_config,
    mercure_options,
    mercure_actions,
    mercure_study,
    mercure_info,
)

# Create local logger instance
logger = daiquiri.getLogger("generate_taskfile")


def compose_task(
    uid: str,
    uid_type: Literal["series", "study"],
    triggered_rules: Dict[str, Literal[True]],
    current_rule: str,
    tags_list: Dict[str, str],
    target: str,
) -> Task:
    return {
        "info": add_info(uid, uid_type, triggered_rules, tags_list),
        "dispatch": add_dispatching(uid, current_rule, tags_list, target) or {},  # type: ignore
        "process": add_processing(uid, current_rule, tags_list) or {},  # type: ignore
        "study": EmptyDict(),
    }


def add_processing(uid: str, applied_rule: str, tags_list) -> Optional[Module]:

    # If the applied_rule name is empty, don't add processing information (rules with processing action always have applied_rule set)
    if not applied_rule:
        return None

    logger.info("add_processing")
    applied_rule_info: Rule = config.mercure[mercure_config.RULES][applied_rule]
    logger.info(applied_rule_info)

    if applied_rule_info.get(mercure_rule.ACTION, mercure_actions.PROCESS) in (
        mercure_actions.PROCESS,
        mercure_actions.BOTH,
    ):
        logger.info("adding processing section")
        # TODO: This should be changed into an array?
        # Get the module that should be triggered
        module: str = applied_rule_info.get("processing_module", "")
        logger.info("module:")
        logger.info(module)

        # Get the configuration on this module
        module_config = config.mercure[mercure_config.MODULES].get(module, {})

        logger.info({"module_config": module_config})

        # TODO: Probably Still incomplete, but this seems to make the current processing happy
        return module_config

        # = config.mercure[mercure_config.MODULES].get(module,{})
        # task_json[mercure_sections.INFO].update({"module": module })

    logger.info("finished adding processing section")
    return None


def add_dispatching(uid: str, applied_rule: str, tags_list, target: str) -> Optional[TaskDispatch]:

    if not applied_rule and not target:
        # applied_rule and target should not be empty at the same time!
        logger.warning(f"Applied_rule and target empty. Cannot add dispatch information for UID {uid}")
        return None

    if isinstance(applied_rule, dict):
        applied_rule = next(iter(applied_rule.keys()))

    # If no target is provided already (as done in routing-only mode), read the target defined in the applied rule
    if not target:
        target = config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.TARGET, "")

    # Fill the dispatching section, if routing has been selected and a target has been provided
    if (
        config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION, mercure_actions.PROCESS)
        in (mercure_actions.ROUTE, mercure_actions.BOTH)
    ) and target:
        target_info: Target = config.mercure[mercure_config.TARGETS][target]
        return {
            "target_name": target,
            "target_ip": target_info["ip"],
            "target_port": target_info["port"],
            "target_aet_target": target_info.get("aet_target", "ANY-SCP"),
            "target_aet_source": target_info.get("aet_source", "mercure"),
            "retries": None,
            "next_retry_at": None,
        }

    return None


def add_info(
    uid: str,
    uid_type: Literal["series", "study"],
    triggered_rules: Union[Dict[str, Literal[True]], str],
    tags_list: Dict[str, str],
) -> TaskInfo:
    return {
        "uid": uid,
        "uid_type": uid_type,
        "triggered_rules": triggered_rules,
        "mrn": tags_list.get("PatientID", mercure_options.MISSING),
        "acc": tags_list.get("AccessionNumber", mercure_options.MISSING),
        "mercure_version": mercure_defs.VERSION,
        "mercure_appliance": config.mercure["appliance_name"],
        "mercure_server": socket.gethostname(),
    }


def create_study_task(folder_name: str, applied_rule: str, study_UID: str, tags_list: Dict[str, str]) -> bool:
    """Generate task file with information on the study"""

    task_filename = folder_name + mercure_names.TASKFILE

    # TODO: Move into add_... function
    study_info: TaskStudy = {
        "study_uid": study_UID,
        "complete_trigger": config.mercure["rules"][applied_rule]["study_trigger_condition"],
        "complete_required_series": config.mercure["rules"][applied_rule]["study_trigger_series"],
        "creation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_receive_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "received_series": [tags_list.get("SeriesDescription", mercure_options.INVALID)],
        "complete_force": "False",
    }

    task_json: Task = {
        "info": add_info(study_UID, "study", applied_rule, tags_list),
        "dispatch": EmptyDict(),
        "process": EmptyDict(),
        "study": study_info,
    }
    # TODO: Incomplete

    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(
            monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}"
        )
        return False

    return True


def update_study_task(folder_name: str, applied_rule: str, study_UID, tags_list: Dict[str, str]) -> bool:
    """Update the study task file with information from the latest received series"""

    series_description = tags_list.get("SeriesDescription", mercure_options.INVALID)
    task_filename = folder_name + mercure_names.TASKFILE

    # Load existing task file. Raise error if it does not exist
    try:
        with open(task_filename, "r") as task_file:
            task_json: Task = json.load(task_file)
            if len(task_json.get("study", {})) == 0:
                raise Exception("Study information is missing.")
    except:
        error_message = f"Unable to open task file {task_filename}"
        logger.error(error_message)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    # Ensure that the task file contains the study information
    if not (mercure_sections.STUDY in task_json):
        error_message = f"Study information missing in task file {task_filename}"
        logger.error(error_message)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    study = cast(TaskStudy, task_json["study"])

    # Remember the time when the last series was received, as needed to determine completion on timeout
    study["last_receive_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Remember all received series descriptions, as needed to determine completion on received series
    if (mercure_study.RECEIVED_SERIES in task_json["study"]) and (isinstance(study["received_series"], list)):
        study["received_series"].append(series_description)
    else:
        study["received_series"] = [series_description]

    # Safe the updated file back to disk
    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        error_message = f"Unable to write task file {task_filename}"
        logger.error(error_message)
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    return True


def create_series_task(
    folder_name: str,
    triggered_rules: Dict[str, Literal[True]],
    current_rule: str,
    series_UID: str,
    tags_list: Dict[str, str],
    target: str,
) -> bool:
    """Create task file for the received series"""

    # For routing-only: target is string containing the target name and current_rule is empty, as multiple rules could be dispatching to the target
    # For processing-only and both: target is empty and current_rule contains the name of the rule that is being processed

    task_filename = folder_name + mercure_names.TASKFILE
    task_json = compose_task(series_UID, "series", triggered_rules, current_rule, tags_list, target)

    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(
            monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}"
        )
        return False

    return True
