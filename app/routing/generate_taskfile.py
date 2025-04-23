"""
generate_taskfile.py
====================
Helper functions for generating task files in json format,
which describe the job to be done and maintain a journal of the executed actions.
"""

# Standard python includes
import json
import pprint
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

# App-specific includes
import common.config as config
import common.monitor as monitor
from common.constants import mercure_actions, mercure_defs, mercure_names, mercure_options, mercure_rule
from common.helper import get_now_str
from common.types import EmptyDict, Rule, Task, TaskDispatch, TaskDispatchStatus, TaskInfo, TaskProcessing, TaskStudy
from typing_extensions import Literal

# Create local logger instance
logger = config.get_logger()


def compose_task(
    task_id: str,
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
    logger.debug("Composing task.")

    task = Task(
        id=task_id,
        # Add general information about the job
        info=add_info(uid, uid_type, triggered_rules, applied_rule, tags_list),
        # Add dispatch information -- completed only if the job includes a dispatching step
        dispatch=add_dispatching(task_id, uid, applied_rule, target) or cast(EmptyDict, {}),
        # Add processing information -- completed only if the job includes a processing step
        process=add_processing(applied_rule) or cast(EmptyDict, {}),
        # Add information about the study, included all collected series
        study=add_study(uid, uid_type, applied_rule, tags_list) or cast(EmptyDict, {}),
    )
    # task.dispatch = "foo"
    logger.debug("Generated task:")
    logger.debug(pprint.pformat(task.dict()))
    return task


def add_processing(applied_rule: str) -> Optional[Union[TaskProcessing, List[TaskProcessing]]]:
    """
    Adds information about the desired processing step into the task file,
    which is evaluated by the processing module
    """
    # If the applied_rule name is empty, don't add processing information
    # (rules with processing steps always have applied_rule set)
    if not applied_rule:
        return None

    applied_rule_info: Rule = config.mercure.rules[applied_rule]
    logger.debug(f"Applied rule info: {applied_rule_info}")

    if applied_rule_info.action not in (
        mercure_actions.PROCESS,
        mercure_actions.BOTH,
    ):
        return None

    # TODO: Revise this part. Needs to be prepared for sequential execution of modules

    # Get the name of the module that should be triggered
    module_names: List[str] = []
    if isinstance(applied_rule_info.processing_module, str):
        module_names = [applied_rule_info.processing_module]
    else:
        module_names = applied_rule_info.processing_module

    logger.info(f"module: {module_names}")

    process_infos = []
    for i, module_name in enumerate(module_names):
        # Get the configuration of this module
        if module_name not in config.mercure.modules:
            logger.warning(f"Module {module_name} not found in configuration modules ({list(config.mercure.modules.keys())})")
        module_config = config.mercure.modules.get(module_name, None)

        # Compose the processing settings that should be used (module level + rule level)
        settings: Dict[str, Any] = {}
        if module_config is not None:
            settings.update(module_config.settings)

        if isinstance(applied_rule_info.processing_settings, list):
            if i < len(applied_rule_info.processing_settings):
                settings.update(applied_rule_info.processing_settings[i])
        else:
            settings.update(applied_rule_info.processing_settings)

        # Store in the target structure
        process_info: TaskProcessing = TaskProcessing(
            module_name=module_name,
            module_config=module_config,
            settings=settings,
            retain_input_images=applied_rule_info.processing_retain_images,
        )
        process_infos.append(process_info)
    if len(process_infos) > 1:
        return process_infos
    return process_infos[0]


def add_study(
    uid: str, uid_type: Literal["series", "study"], applied_rule: str, tags_list: Dict[str, str]
) -> Optional[TaskStudy]:
    """
    Adds study information into the task file. Returns nothing if the task is a series-level task
    """
    # If the current task is a series task, then don't add study information
    if uid_type == "series":
        return None

    study_info: TaskStudy = TaskStudy(
        study_uid=uid,
        complete_trigger=config.mercure.rules[applied_rule].study_trigger_condition,
        complete_required_series=config.mercure.rules[applied_rule].study_trigger_series,
        creation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        last_receive_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        received_series=[tags_list.get("SeriesDescription", mercure_options.INVALID)],
        received_series_uid=[tags_list.get("SeriesInstanceUID", mercure_options.INVALID)],
        complete_force=False,
        complete_force_action=config.mercure.rules[applied_rule].study_force_completion_action,
    )

    return study_info


def add_dispatching(
    task_id: str, uid: str, applied_rule: str,  target: Union[str, List[str]]
) -> Optional[TaskDispatch]:
    """
    Adds information about the desired dispatching step into the task file, which is evaluated by the dispatcher.
    For series-level dispatching, the target information is provided in string "target", as dispatch operations
    from multiple rules to the same target are combined (to avoid double sending). In all other cases, the
    applied_rule is provided and the target information is taken from the rule definition.
    """
    logger.debug("Maybe adding dispatching...")
    perform_dispatch = False

    if not applied_rule and not target:
        # applied_rule and target should not be empty at the same time!
        logger.warning(f"Applied_rule and target empty. Cannot add dispatch information for UID {uid}")
        return None

    targets_used: List[str] = []
    if isinstance(target, str):
        # Only insert string into list if it is not empty
        if target:
            targets_used = [target]
    else:
        targets_used = target

    # Check if a target string is provided (i.e., job is from series-level dispatching).
    # If so, the images should be dispatched in any case
    if len(targets_used) > 0:
        logger.debug(f"Adding dispatching info because series-level target {target} specified")
        perform_dispatch = True
    else:
        # If no target string is provided, read the target defined in the provided applied rule
        rule_target = config.mercure.rules[applied_rule].target
        if isinstance(rule_target, str):
            targets_used = [rule_target]
        else:
            targets_used = rule_target

        # Applied_rule involves dispatching and target has been set? Then go forward with dispatching
        if (
            config.mercure.rules[applied_rule].get(mercure_rule.ACTION, mercure_actions.PROCESS)
            in (mercure_actions.ROUTE, mercure_actions.BOTH)
        ) and len(targets_used) > 0:
            logger.debug(f"Adding dispatching info because rule specified target {target}")
            perform_dispatch = True

    # If dispatching should not be performed, just return
    if not perform_dispatch:
        logger.debug("Not adding dispatch information.")
        return None

    target_status: Dict[str, TaskDispatchStatus] = {}
    current_time = get_now_str()
    for target_item in targets_used:
        # logger.info(f"Adding target {target_item} to dispatching info")
        # Check if all selected targets actually exist in the configuration (could have been deleted by now)
        if not config.mercure.targets.get(target_item, {}):
            logger.error(f"Target {target_item} does not exist for UID {uid}", task_id)  # handle_error
            return None
        target_status[target_item] = TaskDispatchStatus(state="waiting", time=current_time)

    # All looks good, fill the dispatching section and return it
    return TaskDispatch(
        target_name=targets_used,
        status=target_status,
        retries=None,
        next_retry_at=None,
    )


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
    return TaskInfo(
        action=task_action,
        uid=uid,
        uid_type=uid_type,
        triggered_rules=triggered_rules,
        applied_rule=applied_rule,
        patient_name=tags_list.get("PatientName", mercure_options.MISSING),
        mrn=tags_list.get("PatientID", mercure_options.MISSING),
        acc=tags_list.get("AccessionNumber", mercure_options.MISSING),
        sender_address=tags_list.get("SenderAddress", mercure_options.MISSING),
        sender_aet=tags_list.get("SenderAET", mercure_options.MISSING),
        receiver_aet=tags_list.get("ReceiverAET", mercure_options.MISSING),
        device_serial_number=tags_list.get("DeviceSerialNumber"),
        mercure_version=mercure_defs.VERSION,
        mercure_appliance=config.mercure.appliance_name,
        mercure_server=socket.gethostname(),
    )


def create_series_task(
    task_id: str,
    folder_name: Path,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    series_UID: str,
    tags_list: Dict[str, str],
    target: str,
) -> bool:
    """
    Writes a task file for the received series, containing all information needed by the processor and dispatcher.
    Additional information is written into the file as well
    """
    # Compose the JSON content for the file
    task = compose_task(task_id, series_UID, "series", triggered_rules, applied_rule, tags_list, target)
    monitor.send_update_task(task)

    task_filename = folder_name / mercure_names.TASKFILE
    try:
        with open(task_filename, "w") as task_file:
            json.dump(task.dict(), task_file)
    except Exception:
        logger.error(
            f"Unable to create series task file {task_filename} with contents {task.dict()}", task.id
        )  # handle_error
        return False
    return True


def create_study_task(
    task_id: str,
    target_folder: Path,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    study_UID: str,
    tags_list: Dict[str, str],
) -> bool:
    """
    Generate task file with information on the study
    """
    # Compose the JSON content for the file
    task = compose_task(task_id, study_UID, "study", triggered_rules, applied_rule, tags_list, "")
    monitor.send_update_task(task)

    task_filename = target_folder / mercure_names.TASKFILE
    logger.debug(f"Writing study task file {task_filename}")
    try:
        task.to_file(task_filename)
    except Exception:
        logger.error(f"Unable to create study task file {task_filename}", task.id)  # handle_error
        return False

    return True


def update_study_task(
    task_id: str,
    folder: Path,
    triggered_rules: Dict[str, Literal[True]],
    applied_rule: str,
    study_UID: str,
    tags_list: Dict[str, str],
) -> Tuple[bool, str]:
    """
    Update the study task file with information from the latest received series
    """
    series_description = tags_list.get("SeriesDescription", mercure_options.INVALID)
    series_uid = tags_list.get("SeriesInstanceUID", mercure_options.INVALID)
    task_filename = folder / mercure_names.TASKFILE

    # Load existing task file. Raise error if it does not exist
    try:
        task = Task.from_file(task_filename)
    except Exception:
        logger.error(f"Unable to open study task file {task_filename}", task_id)  # handle_error
        return False, ""

    # Ensure that the task file contains the study information
    if not task.study:
        logger.error(f"Study information missing in task file {task_filename}", task_id)  # handle_error
        return False, ""

    study = cast(TaskStudy, task.study)

    # Remember the time when the last series was received, as needed to determine completion on timeout
    study.last_receive_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Remember all received series descriptions, as needed to determine completion on received series
    if study.received_series and (isinstance(study.received_series, list)):
        study.received_series.append(series_description)
    else:
        study.received_series = [series_description]

    # Also remember the received SeriesUIDs for information purpose
    if study.received_series_uid and (isinstance(study.received_series_uid, list)):
        study.received_series_uid.append(series_uid)
    else:
        study.received_series_uid = [series_uid]

    # Safe the updated file back to disk
    try:
        task.to_file(task_filename)
    except Exception:
        logger.exception(f"Unable to write task file {task_filename}", task.id)  # handle_error
        return False, ""

    monitor.send_update_task(task)

    return True, task.id
