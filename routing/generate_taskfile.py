import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri
import socket 

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

    if (config.mercure[mercure_config.RULES][applied_rule].get(mercure_rule.ACTION,mercure_actions.PROCESS)==mercure_actions.PROCESS):
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


def create_study_task(folder_name):
    pass
