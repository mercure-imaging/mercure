"""
generate_taskfile.py
====================
Helper functions for generating task files in json format, which describe the job to be done and maintain a journal of the executed actions.
"""

# Standard python includes
import os
from pathlib import Path
import traceback
import uuid
import json
import shutil
import daiquiri
import socket
from datetime import datetime

# from mypy_extensions import TypedDict
from typing_extensions import Literal
from typing import Dict, Optional, Union, List, cast
from common.types import *

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
    applied_rule: str,
    tags_list: Dict[str, str],
    target: str,
) -> Task:
    """
    Composes the JSON content that is written into a task file when submitting a job (for processing, dispatching, or both)
    """
    return {
        # Add general information about the job
        "info": add_info(uid, uid_type, triggered_rules, applied_rule, tags_list),
        # Add dispatch information -- completed only if the job includes a dispatching step
        # type: ignore
        "dispatch": add_dispatching(uid, applied_rule, tags_list, target) or {},
        # Add processing information -- completed only if the job includes a processing step
        # type: ignore
        "process": add_processing(uid, applied_rule, tags_list) or {},
        # Add information about the study, included all collected series
        "study": add_study(uid, uid_type, applied_rule, tags_list) or EmptyDict(),
    }


def add_processing(uid: str, applied_rule: str, tags_list: Dict[str, str]) -> Optional[Module]:
    """
    Adds information about the desired processing step into the task file, which is evaluated by the processing module
    """
    # If the applied_rule name is empty, don't add processing information (rules with processing steps always have applied_rule set)
    if not applied_rule:
        return None

    applied_rule_info: Rule = config.mercure.rules[applied_rule]
    logger.info(applied_rule_info)

    if applied_rule_info.get(mercure_rule.ACTION, mercure_actions.PROCESS) in (
        mercure_actions.PROCESS,
        mercure_actions.BOTH,
    ):
        # Get the module that should be triggered
        # TODO: Revise this part. Needs to be prepared for sequential execution of modules
        module: str = applied_rule_info.get("processing_module", "")
        logger.info(f"module: {module}")

        # Get the configuration of this module
        module_config: Module = config.mercure.modules.get(module, {})

        logger.info({"module_config": module_config})

        # TODO: Probably Still incomplete, but this seems to make the current processing happy
        # TODO: Write the setting into a subsection and also store the module name

        return module_config

    return None


def add_study(
    uid: str, uid_type: Literal["series", "study"], applied_rule: str, tags_list: Dict[str, str]
) -> Optional[TaskStudy]:
    """
    Adds study information into the task file. Returns nothing if the task is a series-level task
    """
    # If the current task is a series task, then don't add study information
    if uid_type == "series":
        return None

    study_info: TaskStudy = {
        "study_uid": uid,
        "complete_trigger": config.mercure.rules[applied_rule]["study_trigger_condition"],
        "complete_required_series": config.mercure.rules[applied_rule]["study_trigger_series"],
        "creation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_receive_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "received_series": [tags_list.get("SeriesDescription", mercure_options.INVALID)],
        "complete_force": "False",
    }

    return study_info


def add_dispatching(uid: str, applied_rule: str, tags_list: Dict[str, str], target: str) -> Optional[TaskDispatch]:
    """
    Adds information about the desired dispatching step into the task file, which is evaluated by the dispatcher
    """
    if not applied_rule and not target:
        # applied_rule and target should not be empty at the same time!
        logger.warning(f"Applied_rule and target empty. Cannot add dispatch information for UID {uid}")
        return None

    target_used: str = target

    # If no target is provided already (as done in routing-only mode), read the target defined in the applied rule
    if not target_used:
        target_used = config.mercure.rules[applied_rule].get("target", "")

    # Fill the dispatching section, if routing has been selected and a target has been provided
    if (
        config.mercure.rules[applied_rule].get(mercure_rule.ACTION, mercure_actions.PROCESS)
        in (mercure_actions.ROUTE, mercure_actions.BOTH)
    ) and target_used:
        target_info: Target = config.mercure.targets[target_used]
        return {
            "target_name": target_used,
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
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    tags_list: Dict[str, str],
) -> TaskInfo:
    """
    Adds general information into the task file
    """
    if applied_rule:
        task_action = config.mercure.rules[applied_rule].get("action", "process")
    else:
        task_action = "route"

    return {
        "action": task_action,
        "uid": uid,
        "uid_type": uid_type,
        "triggered_rules": triggered_rules,
        "applied_rule": applied_rule,
        "mrn": tags_list.get("PatientID", mercure_options.MISSING),
        "acc": tags_list.get("AccessionNumber", mercure_options.MISSING),
        "mercure_version": mercure_defs.VERSION,
        "mercure_appliance": config.mercure.appliance_name,
        "mercure_server": socket.gethostname(),
    }


def create_series_task(
    folder_name: str,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    series_UID: str,
    tags_list: Dict[str, str],
    target: str,
) -> bool:
    """
    Writes a task file for the received series, containing all information needed by the processor and dispatcher. Additional information is written into the file as well
    """
    # Compose the JSON content for the file
    task_json = compose_task(series_UID, "series", triggered_rules, applied_rule, tags_list, target)

    task_filename = folder_name + mercure_names.TASKFILE
    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        error_message = f"Unable to create series task file {task_filename}"
        logger.exception(error_message)
        logger.error(task_json)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    return True


def create_study_task(
    folder_name: str,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    study_UID: str,
    tags_list: Dict[str, str],
) -> bool:
    """
    Generate task file with information on the study
    """
    # Compose the JSON content for the file
    task_json = compose_task(study_UID, "study", triggered_rules, applied_rule, tags_list, "")

    task_filename = folder_name + mercure_names.TASKFILE
    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        error_message = f"Unable to create study task file {task_filename}"
        logger.exception(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    return True


def update_study_task(
    folder_name: str,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    study_UID: str,
    tags_list: Dict[str, str],
) -> bool:
    """
    Update the study task file with information from the latest received series
    """
    series_description = tags_list.get("SeriesDescription", mercure_options.INVALID)
    task_filename = folder_name + mercure_names.TASKFILE

    # Load existing task file. Raise error if it does not exist
    try:
        with open(task_filename, "r") as task_file:
            task_json: Task = json.load(task_file)
            if len(task_json.get("study", {})) == 0:
                raise Exception("Study information is missing.")
    except:
        error_message = f"Unable to open study task file {task_filename}"
        logger.exception(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    # Ensure that the task file contains the study information
    if not (mercure_sections.STUDY in task_json):
        error_message = f"Study information missing in task file {task_filename}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
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
        logger.exception(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
        return False

    return True
