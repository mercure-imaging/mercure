"""
send.py
=======
The functions for sending DICOM series
to target destinations.
"""

# Standard python includes
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, cast

import common.config as config
import common.log_helpers as log_helpers
import common.monitor as monitor
import common.notification as notification
import dispatch.target_types as target_types
from common.constants import mercure_events, mercure_names
from common.event_types import FailStage
from common.helper import get_now_str
# App-specific includes
from common.monitor import m_events, severity, task_event
from common.types import Task, TaskDispatch, TaskDispatchStatus
from dispatch.retry import increase_retry, update_dispatch_status
from dispatch.status import is_ready_for_sending
from typing_extensions import Literal

# Create local logger instance
logger = config.get_logger()


# def _create_command(task_id: str, dispatch_info: TaskDispatch, folder: Path) -> Tuple[str, dict, bool]:
#     """Composes the command for calling the dcmsend tool from DCMTK, which is used for sending out the DICOMS."""
#     target_name: str = dispatch_info.get("target_name", "")

#     if isinstance(config.mercure.targets.get(target_name, ""), DicomTarget):
#         # Read the connection information from the configuration
#         target_dicom = cast(DicomTarget, config.mercure.targets.get(target_name))
#         target_ip = target_dicom.ip
#         target_port = target_dicom.port or 104
#         target_aet_target = target_dicom.aet_target or ""
#         target_aet_source = target_dicom.aet_source or ""
#         dcmsend_status_file = Path(folder) / mercure_names.SENDLOG
#         command = f"""dcmsend {target_ip} {target_port} +sd {folder} -aet {target_aet_source} -aec {target_aet_target}
#            -nuc +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"""
#         return command, {}, True

#     elif isinstance(config.mercure.targets.get(target_name, ""), DicomTLSTarget):
#         # Read the connection information from the configuration
#         tls_dicom: DicomTLSTarget = cast(DicomTLSTarget, config.mercure.targets.get(target_name))
#         target_ip = tls_dicom.ip
#         target_port = tls_dicom.port or 104
#         target_aet_target = tls_dicom.aet_target or ""
#         target_aet_source = tls_dicom.aet_source or ""
#         tls_key = tls_dicom.tls_key
#         tls_cert = tls_dicom.tls_cert
#         ca_cert = tls_dicom.ca_cert

#         command = f"""storescu +tls {tls_key} {tls_cert} +cf {ca_cert} {target_ip} {target_port} +sd {folder}
#           -aet {target_aet_source} -aec {target_aet_target} +sp '*.dcm' -to 60"""
#         return command, {}, True

#     elif isinstance(config.mercure.targets.get(target_name, ""), SftpTarget):
#         # Read the connection information from the configuration
#         target_sftp: SftpTarget = cast(SftpTarget, config.mercure.targets.get(target_name))

#         # TODO: Use newly created UUID instead of folder.stem? Would avoid collision during repeated transfer
#         # TODO: is this entirely safe?

#         # After the transfer, create file named ".complete" to indicate that the transfer is complete
#         command = (
#             "sftp -o StrictHostKeyChecking=no "
#             + f""" "{target_sftp.user}@{target_sftp.host}:{target_sftp.folder}" """
#             + f""" <<- EOF
#                     mkdir "{target_sftp.folder}/{folder.stem}"
#                     put -f -r "{folder}"
#                     !touch "/tmp/.complete"
#                     put -f "/tmp/.complete" "{target_sftp.folder}/{folder.stem}/.complete"
# EOF"""
#         )
#         if target_sftp.password:
#             command = f"sshpass -p {target_sftp.password} " + command
#         return command, dict(shell=True, executable="/bin/bash"), False

#     else:
#         logger.error(f"Target in task file does not exist {target_name}", task_id)  # handle_error
#         return "", {}, False


@log_helpers.clear_task_decorator
def execute(
    source_folder: Path,
    success_folder: Path,
    error_folder: Path,
    retry_max,
    retry_delay,
):
    """
    Execute the dcmsend command. It will create a .sending file to indicate that
    the folder is being sent. This is to prevent double sending. If there
    happens any error the .lock file is deleted and an .error file is created.
    Folder with .error files are _not_ ready for sending.
    """
    task_content = is_ready_for_sending(source_folder)
    if not task_content:
        return
    logger.setTask(task_content.id)

    dispatch_info = task_content.dispatch
    if not dispatch_info:
        return
    task_info = task_content.info

    if time.time() < dispatch_info.get("next_retry_at", 0):
        return

    uid = task_info.get("uid", "uid-missing")
    if (uid == "uid-missing"):
        logger.warning(f"Missing information for folder {source_folder}", task_content.id)

    # Ensure that the target_name is a list. Needed just for backwards compatibility
    # (i.e., if the task.json file was created with an older mercure version)
    if isinstance(dispatch_info.target_name, str):
        dispatch_info.target_name = [dispatch_info.target_name]

    if len(dispatch_info.target_name) == 0:
        logger.error(  # handle_error
            f"No targets provided. Unable to dispatch job {uid}",
            task_content.id,
            target="",
        )
        _move_sent_directory(task_content.id, source_folder, error_folder, FailStage.DISPATCHING)
        _trigger_notification(task_content, mercure_events.ERROR)
        return

    for target_item in dispatch_info.target_name:
        if not config.mercure.targets.get(target_item, None):
            logger.error(  # handle_error
                f"Settings for target {target_item} incorrect. Unable to start dispatching of job {uid}",
                task_content.id,
                target=target_item,
            )
            _move_sent_directory(task_content.id, source_folder, error_folder, FailStage.DISPATCHING)
            _trigger_notification(task_content, mercure_events.ERROR)
            return

    # Create a .processing file to indicate that this folder is being sent,
    # otherwise another dispatcher instance would pick it up again
    lock_file = Path(source_folder) / mercure_names.PROCESSING
    try:
        lock_file.touch(exist_ok=False)
    except FileExistsError:
        # Return if the case has already been locked by another instance in the meantime
        return
    except Exception:
        # TODO: Put a limit on these error messages -- log will run full at some point
        logger.error(  # handle_error
            f"Error sending {uid} to {dispatch_info.target_name}, could not create lock file for folder {source_folder}",
            task_content.id,
            target=",".join(dispatch_info.target_name),
        )
        return

    logger.info("---------")
    logger.info(f"Folder {source_folder} is ready for sending")

    # Check if a sendlog file from a previous try exists. If so, remove it
    sendlog = Path(source_folder) / mercure_names.SENDLOG
    if sendlog.exists():
        try:
            sendlog.unlink()
        except Exception:
            logger.error(  # handle_error
                f"Error sending {uid} to {dispatch_info.target_name}: unable to remove former sendlog {sendlog}",
                task_content.id,
            )
            return

    current_status = dispatch_info.status
    # Needed just for backwards compatibility (i.e., if the task.json file was created with an older mercure version)
    if len(current_status) != len(dispatch_info.target_name):
        current_status = {target_item: TaskDispatchStatus(state="waiting", time=get_now_str())
                          for target_item in dispatch_info.target_name}

    for target_item in dispatch_info.target_name:
        if current_status[target_item] and current_status[target_item].state != "complete":  # type: ignore

            # Compose the command for dispatching the results
            target = config.mercure.targets.get(target_item, None)
            if not target:
                logger.error(  # handle_error
                    f"Error sending {uid} to {target_item}: unable to get target information",
                    task_content.id,
                )
                current_status[target_item] = TaskDispatchStatus(state="error", time=get_now_str())  # type: ignore
                continue

            try:
                handler = target_types.get_handler(target)
                file_count = len(list(Path(source_folder).glob(mercure_names.DCMFILTER)))
                monitor.send_task_event(
                    task_event.DISPATCH_BEGIN,
                    task_content.id,
                    file_count,
                    target_item,
                    "Routing job running",
                )
                handler.send_to_target(task_content.id, target, cast(TaskDispatch, dispatch_info), source_folder, task_content)
                monitor.send_task_event(
                    task_event.DISPATCH_COMPLETE,
                    task_content.id,
                    file_count,
                    target_item,
                    "Routing job complete",
                )
                current_status[target_item] = TaskDispatchStatus(state="complete", time=get_now_str())  # type: ignore

            except Exception as e:
                logger.error(  # handle_error
                    f"Error sending uid {uid} in task {task_content.id} to {target_item}:\n {e}",
                    task_content.id,
                    target=target_item,
                )
                current_status[target_item] = TaskDispatchStatus(state="error", time=get_now_str())  # type: ignore

    dispatch_success = True
    for item in current_status:
        if current_status[item].state != "complete":  # type: ignore
            dispatch_success = False
            break

    if not update_dispatch_status(source_folder, current_status):
        logger.error(  # handle_error
            f"Error updating dispatch status for task {uid}",
            task_content.id,
        )

    if dispatch_success:
        # Dispatching of successful
        _move_sent_directory(task_content.id, source_folder, success_folder)
        monitor.send_task_event(task_event.MOVE, task_content.id, 0,
                                str(success_folder) + "/" + str(source_folder.name), "Moved to success folder")
        _trigger_notification(task_content, mercure_events.COMPLETED)
        monitor.send_task_event(monitor.task_event.COMPLETE, task_content.id, 0, "", "Task complete")
        logger.info(f"Done with dispatching folder {source_folder}")

    else:
        # Error during dispatching of job
        retry_increased = increase_retry(source_folder, retry_max, retry_delay)
        if retry_increased:
            lock_file.unlink()
        else:
            logger.info(f"Max retries reached, moving to {error_folder}")
            monitor.send_task_event(task_event.SUSPEND, task_content.id, 0,
                                    ",".join(dispatch_info.target_name), "Max retries reached")
            _move_sent_directory(task_content.id, source_folder, error_folder, FailStage.DISPATCHING)
            monitor.send_task_event(task_event.MOVE, task_content.id, 0,
                                    str(error_folder), "Moved to error folder")
            monitor.send_event(m_events.PROCESSING, severity.ERROR,
                               "Series suspended after reaching max retries")
            _trigger_notification(task_content, mercure_events.ERROR)
            logger.info(f"Dispatching folder {source_folder} not successful")


def _move_sent_directory(task_id, source_folder, destination_folder, fail_stage=None) -> None:
    """
    This check is needed if there is already a folder with the same name
    in the success folder. If so a new directory is create with a timestamp
    as suffix.
    """
    try:
        if (destination_folder / source_folder.name).exists():
            target_folder = destination_folder / (source_folder.name + "_" + datetime.now().isoformat())
            logger.debug(f"Moving {source_folder} to {target_folder}")
            shutil.move(source_folder, target_folder, copy_function=shutil.copy2)
            if fail_stage and not update_fail_stage(target_folder, fail_stage):
                logger.error(f"Error updating fail stage for task {task_id}")
            (Path(target_folder) / mercure_names.PROCESSING).unlink()
        else:
            logger.debug(f"Moving {source_folder} to {destination_folder / source_folder.name}")
            shutil.move(source_folder, destination_folder / source_folder.name)
            if fail_stage and not update_fail_stage(destination_folder / source_folder.name, fail_stage):
                logger.error(f"Error updating fail stage for task {task_id}")
            (destination_folder / source_folder.name / mercure_names.PROCESSING).unlink()
    except Exception:
        logger.error(f"Error moving folder {source_folder} to {destination_folder}", task_id)  # handle_error


def _trigger_notification(task: Task, event: mercure_events) -> None:
    # Select which notifications need to be sent. If applied_rule is not empty, check only this rule. Otherwise,
    # check all rules that are contained in triggered_rules (applied only to series-level dispatching)
    task_info = task.info

    selected_rules: Dict[str, Literal[True]] = {}
    if task_info.applied_rule:
        selected_rules[task_info.applied_rule] = True
    else:
        if not isinstance(task_info.triggered_rules, str):
            selected_rules = task_info.triggered_rules

    for current_rule in selected_rules:
        request_do_send = False
        if (the_rule := config.mercure.rules.get(current_rule)) and the_rule.notification_trigger_completion_on_request:
            if notification.get_task_requested_notification(task):
                request_do_send = True
        notification.trigger_notification_for_rule(
            current_rule,
            task.id,
            event,
            task=task,
            details=notification.get_task_custom_notification(task),
            send_always=request_do_send,
        )


def update_fail_stage(source_folder: Path, fail_stage: FailStage) -> bool:
    in_string = "in" if fail_stage == FailStage.PROCESSING else ""
    target_json_path: Path = source_folder / in_string / mercure_names.TASKFILE
    try:
        with open(target_json_path, "r") as file:
            task: Task = Task(**json.load(file))

        task_info = task.info
        task_info.fail_stage = str(fail_stage)  # type: ignore

        with open(target_json_path, "w") as file:
            json.dump(task.dict(), file)
    except Exception:
        return False

    return True
