import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri
import socket
from datetime import datetime

# App-specific includes
import common.config as config
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.helper as helper
from common.constants import mercure_defs, mercure_names, mercure_sections, mercure_rule, mercure_config, mercure_options, mercure_actions, mercure_study, mercure_info


logger = daiquiri.getLogger("generate_taskfile")


def compose_task(uid, uid_type, triggered_rules, tags_list, target):
    task_json = {}
    task_json.update(add_info(uid, uid_type, triggered_rules, tags_list))
    task_json.update(add_dispatching(triggered_rules, tags_list, target))
    task_json.update(add_processing(triggered_rules, tags_list))
    return task_json


def add_processing(applied_rule, tags_list):
    process_section = {}
    process_section[mercure_sections.PROCESS] = {}

    if config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION, mercure_actions.PROCESS) in (mercure_actions.PROCESS, mercure_actions.BOTH):

        # TODO: This should be changed into an array
        module = config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.PROCESSING_MODULE, "")

        # TODO: Still incomplete
        process_section[mercure_sections.PROCESS]["modules"] = [module]
        process_section[mercure_sections.PROCESS]["settings"] = {}

        # = config.mercure[mercure_config.MODULES].get(module,{})
        # task_json[mercure_sections.INFO].update({"module": module })

    return process_section


def add_dispatching(applied_rule, tags_list, target):
    dispatch_section = {}
    dispatch_section[mercure_sections.DISPATCH] = {}

    # If no target is provided already (as done in routing-only mode), read the target defined in the applied rule
    if not target:
        target = config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.TARGET, "")

    # Fill the dispatching section, if routing has been selected and a target has been provided
    if (config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION, mercure_actions.PROCESS) in (mercure_actions.ROUTE, mercure_actions.BOTH)) and target:
        dispatch_section[mercure_sections.DISPATCH]["target_name"] = target
        dispatch_section[mercure_sections.DISPATCH]["target_ip"] = config.mercure[mercure_config.TARGETS][target]["ip"]
        dispatch_section[mercure_sections.DISPATCH]["target_port"] = config.mercure[mercure_config.TARGETS][target]["port"]
        dispatch_section[mercure_sections.DISPATCH]["target_aet_target"] = config.mercure[mercure_config.TARGETS][target].get("aet_target", "ANY-SCP")
        dispatch_section[mercure_sections.DISPATCH]["target_aet_source"] = config.mercure[mercure_config.TARGETS][target].get("aet_source", "mercure")

    return dispatch_section


def add_info(uid, uid_type, triggered_rules, tags_list):
    info_section = {}
    info_section[mercure_sections.INFO] = {}
    info_section[mercure_sections.INFO][mercure_info.UID] = uid
    info_section[mercure_sections.INFO][mercure_info.UID_TYPE] = uid_type
    info_section[mercure_sections.INFO][mercure_info.TRIGGERED_RULES] = triggered_rules
    info_section[mercure_sections.INFO][mercure_info.MRN] = tags_list.get("PatientID", mercure_options.MISSING)
    info_section[mercure_sections.INFO][mercure_info.ACC] = tags_list.get("AccessionNumber", mercure_options.MISSING)
    info_section[mercure_sections.INFO][mercure_info.MERCURE_VERSION] = mercure_defs.VERSION
    info_section[mercure_sections.INFO][mercure_info.MERCURE_APPLIANCE] = config.mercure["appliance_name"]
    info_section[mercure_sections.INFO][mercure_info.MERCURE_SERVER] = socket.gethostname()
    return info_section


def create_study_task(folder_name, applied_rule, study_UID, tags_list):
    """Generate task file with information on the study"""

    task_filename = folder_name + mercure_names.TASKFILE

    # TODO: Move into add_... function
    study_info = {}
    study_info[mercure_study.STUDY_UID] = study_UID
    study_info[mercure_study.COMPLETE_TRIGGER] = config.mercure[mercure_config.RULES][applied_rule]["study_trigger_condition"]
    study_info[mercure_study.COMPLETE_REQUIRED_SERIES] = config.mercure[mercure_config.RULES][applied_rule]["study_trigger_series"]
    study_info[mercure_study.CREATION_TIME] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    study_info[mercure_study.LAST_RECEIVE_TIME] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    study_info[mercure_study.RECEIVED_SERIES] = [tags_list.get("SeriesDescription", mercure_options.INVALID)]

    task_json = {}
    task_json[mercure_sections.STUDY] = study_info
    task_json.update(add_info(study_UID, mercure_options.STUDY, applied_rule, tags_list))
    # TODO: Incomplete

    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}")
        return False

    return True


def update_study_task(folder_name, applied_rule, study_UID, tags_list):
    """Update the study task file with information from the latest received series"""

    series_description = tags_list.get("SeriesDescription", mercure_options.INVALID)
    task_filename = folder_name + mercure_names.TASKFILE

    # Load existing task file. Raise error if it does not exist
    try:
        with open(task_filename, "r") as task_file:
            task_json = json.load(task_file)
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

    # Remember the time when the last series was received, as needed to determine completion on timeout
    task_json[mercure_sections.STUDY][mercure_study.LAST_RECEIVE_TIME] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Remember all received series descriptions, as needed to determine completion on received series
    if (mercure_study.RECEIVED_SERIES in task_json[mercure_sections.STUDY]) and (isinstance(task_json[mercure_sections.STUDY][mercure_study.RECEIVED_SERIES], list)):
        task_json[mercure_sections.STUDY][mercure_study.RECEIVED_SERIES].append(series_description)
    else:
        task_json[mercure_sections.STUDY][mercure_study.RECEIVED_SERIES] = [series_description]

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


def create_series_task(folder_name, triggered_rules, series_UID, tags_list, target):
    """Create task file for the received series"""

    # For routing-only: triggered_rules is dict and target is string containing the target name
    # For processing-only and both: triggered_rule is string and target is empty

    task_filename = folder_name + mercure_names.TASKFILE
    task_json = compose_task(series_UID, mercure_options.SERIES, triggered_rules, tags_list, target)

    try:
        with open(task_filename, "w") as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}")
        return False

    return True
