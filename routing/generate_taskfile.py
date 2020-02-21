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
from common.constants import mercure_defs, mercure_names, mercure_sections, mercure_rule, mercure_config, mercure_options


logger = daiquiri.getLogger("generate_taskfile")


def generate_taskfile_route(target,series_UID,applied_rule,tags_list):
    task_json=add_info(tags_list)
    task_json[mercure_sections.DISPATCH]={}
    task_json[mercure_sections.DISPATCH]["target_ip"]        =config.mercure[mercure_config.TARGETS][target]["ip"]
    task_json[mercure_sections.DISPATCH]["target_port"]      =config.mercure[mercure_config.TARGETS][target]["port"]
    task_json[mercure_sections.DISPATCH]["target_aet_target"]=config.mercure[mercure_config.TARGETS][target].get("aet_target","ANY-SCP")
    task_json[mercure_sections.DISPATCH]["target_aet_source"]=config.mercure[mercure_config.TARGETS][target].get("aet_source","mercure")
    task_json[mercure_sections.DISPATCH]["target_name"]      =target
    task_json[mercure_sections.DISPATCH]["applied_rule"]     =applied_rule
    task_json[mercure_sections.DISPATCH]["series_uid"]       =series_UID
    return task_json


def add_info(tags_list):
    info_section = {}
    info_section[mercure_sections.INFO]={}
    info_section[mercure_sections.INFO]["mrn"]=tags_list.get("PatientID",mercure_options.MISSING)
    info_section[mercure_sections.INFO]["acc"]=tags_list.get("AccessionNumber",mercure_options.MISSING)
    return info_section
