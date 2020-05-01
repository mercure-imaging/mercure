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
from common.constants import mercure_defs, mercure_names, mercure_sections, mercure_rule, mercure_config, mercure_options, mercure_actions


logger = daiquiri.getLogger("generate_taskfile")


def generate_taskfile_route(uid, uid_type, applied_rule, tags_list, target):
    task_json={}
    task_json.update(add_info(uid, uid_type, applied_rule, tags_list))
    task_json.update(add_dispatching(applied_rule, tags_list, target))
    return task_json


def generate_taskfile_process(uid, uid_type, applied_rule, tags_list):
    task_json={}
    task_json.update(add_info(uid, uid_type, applied_rule, tags_list))

    if (config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION,mercure_actions.PROCESS) in (mercure_actions.PROCESS, mercure_actions.BOTH) ):
        module = config.mercure[mercure_config.RULES][applied_rule].get('processing_module',"")
        task_json[mercure_sections.INFO].update({"module": module })
        task_json[mercure_sections.PROCESS] = config.mercure[mercure_config.MODULES].get(module,{})

    if (config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION,mercure_actions.PROCESS)==mercure_actions.BOTH):
        target=config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.TARGET,"")
        task_json.update(add_dispatching(applied_rule, tags_list, target))

    return task_json


def add_dispatching(applied_rule, tags_list, target):
    dispatch_section = {}
    dispatch_section[mercure_sections.DISPATCH]={}
    dispatch_section[mercure_sections.DISPATCH]["target_name"]      =target
    dispatch_section[mercure_sections.DISPATCH]["target_ip"]        =config.mercure[mercure_config.TARGETS][target]["ip"]
    dispatch_section[mercure_sections.DISPATCH]["target_port"]      =config.mercure[mercure_config.TARGETS][target]["port"]
    dispatch_section[mercure_sections.DISPATCH]["target_aet_target"]=config.mercure[mercure_config.TARGETS][target].get("aet_target","ANY-SCP")
    dispatch_section[mercure_sections.DISPATCH]["target_aet_source"]=config.mercure[mercure_config.TARGETS][target].get("aet_source","mercure")
    return dispatch_section


def add_info(uid, uid_type, applied_rule, tags_list):
    info_section = {}
    info_section[mercure_sections.INFO]={}
    info_section[mercure_sections.INFO]["uid"]=uid
    info_section[mercure_sections.INFO]["uid_type"]=uid_type
    info_section[mercure_sections.INFO]["applied_rule"]=applied_rule
    info_section[mercure_sections.INFO]["mrn"]=tags_list.get("PatientID",mercure_options.MISSING)
    info_section[mercure_sections.INFO]["acc"]=tags_list.get("AccessionNumber",mercure_options.MISSING)
    info_section[mercure_sections.INFO]["mercure_version"]=mercure_defs.VERSION
    info_section[mercure_sections.INFO]["mercure_appliance"]=config.mercure["appliance_name"]
    info_section[mercure_sections.INFO]["mercure_server"]=socket.gethostname() 
    return info_section


def create_study_task(folder_name, applied_rule, study_UID, tags_list):
    """Generate task file with information on the study"""

    task_filename = folder_name + mercure_names.TASKFILE

    study_info={}
    study_info["study_uid"]               =study_UID
    study_info["complete_trigger"]        =config.mercure[mercure_config.RULES][applied_rule]["study_trigger_condition"]
    study_info["complete_required_series"]=config.mercure[mercure_config.RULES][applied_rule]["study_trigger_series"]
    study_info["creation_time"]           =datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    task_json = {}
    task_json[mercure_sections.STUDY]=study_info
    task_json.update(add_info(study_UID, mercure_options.STUDY, applied_rule, tags_list))
    
    try:
        with open(task_filename, 'w') as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}")
        return False

    return True


def create_series_task_processing(folder_name, applied_rule, series_UID, tags_list):
    """Generate task file with processing information for the series"""

    task_filename = folder_name + mercure_names.TASKFILE
    task_json = generate_taskfile_process(series_UID, mercure_options.SERIES, applied_rule, tags_list)

    try:
        with open(task_filename, 'w') as task_file:
            json.dump(task_json, task_file)
    except:
        logger.error(f"Unable to create task file {task_filename}")
        monitor.send_event(monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to create task file {task_filename}")
        return False

    return True
        
