"""
send.py
=======
The functions for sending DICOM series
to target destinations.
"""

# Standard python includes
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from shlex import split
from subprocess import PIPE, CalledProcessError, check_output
from typing import Dict, Tuple, cast
from typing_extensions import Literal

# App-specific includes
from common.monitor import task_event, m_events, severity
from dispatch.retry import increase_retry
from dispatch.status import is_ready_for_sending
from common.constants import mercure_names
from common.types import DicomTarget, SftpTarget, Task, TaskDispatch, TaskInfo, Rule
import common.config as config
import common.monitor as monitor
import common.notification as notification
import common.log_helpers as log_helpers
from common.constants import (
    mercure_events,
)
import dispatch.target_types as target_types

# Create local logger instance
logger = config.get_logger()


def _create_command(task_id: str, dispatch_info: TaskDispatch, folder: Path) -> Tuple[str, dict, bool]:
    """Composes the command for calling the dcmsend tool from DCMTK, which is used for sending out the DICOMS."""
    target_name: str = dispatch_info.get("target_name", "")

    if isinstance(config.mercure.targets.get(target_name, ""), DicomTarget):
        # Read the connection information from the configuration
        target_dicom = cast(DicomTarget, config.mercure.targets.get(target_name))
        target_ip = target_dicom.ip
        target_port = target_dicom.port or 104
        target_aet_target = target_dicom.aet_target or ""
        target_aet_source = target_dicom.aet_source or ""
        dcmsend_status_file = Path(folder) / mercure_names.SENDLOG
        command = f"""dcmsend {target_ip} {target_port} +sd {folder} -aet {target_aet_source} -aec {target_aet_target} -nuc +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"""
        return command, {}, True

    elif isinstance(config.mercure.targets.get(target_name, ""), SftpTarget):
        # Read the connection information from the configuration
        target_sftp: SftpTarget = cast(SftpTarget, config.mercure.targets.get(target_name))

        # TODO: Use newly created UUID instead of folder.stem? Would avoid collission during repeated transfer
        # TODO: is this entirely safe?

        # After the transfer, create file named ".complete" to indicate that the transfer is complete
        command = (
            "sftp -o StrictHostKeyChecking=no "
            + f""" "{target_sftp.user}@{target_sftp.host}:{target_sftp.folder}" """
            + f""" <<- EOF
                    mkdir "{target_sftp.folder}/{folder.stem}"
                    put -f -r "{folder}"
                    !touch "/tmp/.complete"
                    put -f "/tmp/.complete" "{target_sftp.folder}/{folder.stem}/.complete"
EOF"""
        )
        if target_sftp.password:
            command = f"sshpass -p {target_sftp.password} " + command
        return command, dict(shell=True, executable="/bin/bash"), False

    else:
        logger.error(f"Target in task file does not exist {target_name}", task_id)  # handle_error
        return "", {}, False


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
    task_info = task_content.info

    delay: float = 0
    if dispatch_info and dispatch_info.next_retry_at:
        delay = dispatch_info.next_retry_at

    if dispatch_info and time.time() >= delay:
        uid = task_info.get("uid", "uid-missing")
        target_name: str = dispatch_info.get("target_name", "target_name-missing")

        if (uid == "uid-missing") or (target_name == "target_name-missing"):
            logger.warning(f"Missing information for folder {source_folder}", task_content.id)

        # Create a .processing file to indicate that this folder is being sent,
        # otherwise another dispatcher instance would pick it up again
        lock_file = Path(source_folder) / mercure_names.PROCESSING
        try:
            lock_file.touch(exist_ok=False)
        except FileExistsError:
            # Return if the case has already been locked by another instance in the meantime
            return
        except:
            # TODO: Put a limit on these error messages -- log will run full at some point
            logger.error(  # handle_error
                f"Error sending {uid} to {target_name}, could not create lock file for folder {source_folder}",
                task_content.id,
                target=target_name,
            )
            return

        logger.info("---------")
        logger.info(f"Folder {source_folder} is ready for sending")

        # Check if a sendlog file from a previous try exists. If so, remove it
        sendlog = Path(source_folder) / mercure_names.SENDLOG
        if sendlog.exists():
            try:
                sendlog.unlink()
            except:
                logger.error(  # handle_error
                    f"Error sending {uid} to {target_name}: unable to remove former sendlog {sendlog}",
                    task_content.id,
                )
                return

        # Compose the command for dispatching the results
        target = config.mercure.targets.get(dispatch_info.get("target_name", ""), None)

        if target is None:
            logger.error(  # handle_error
                f"Settings for target {target_name} incorrect. Unable to dispatch job {uid}",
                task_content.id,
                target=target_name,
            )
            _move_sent_directory(task_content.id, source_folder, error_folder)
            _trigger_notification(task_content, mercure_events.ERROR)
            return

        handler = target_types.get_handler(target)

        try:
            file_count = len(list(Path(source_folder).glob(mercure_names.DCMFILTER)))
            monitor.send_task_event(
                task_event.DISPATCH_BEGIN,
                task_content.id,
                file_count,
                target_name,
                "Routing job running",
            )
            result = handler.send_to_target(task_content.id, target, dispatch_info, source_folder)
            monitor.send_task_event(
                task_event.DISPATCH_COMPLETE,
                task_content.id,
                file_count,
                "",
                "Routing job complete",
            )

            monitor.send_task_event(task_event.MOVE, task_content.id, 0, str(success_folder), "Moved to success folder")
            _move_sent_directory(task_content.id, source_folder, success_folder)

            _trigger_notification(task_content, mercure_events.COMPLETED)
            monitor.send_task_event(monitor.task_event.COMPLETE, task_content.id, 0, "", "Task complete")

        except Exception as e:
            logger.error(  # handle_error
                f"Error sending uid {uid} in task {task_content.id} to {target_name}:\n {e}",
                task_content.id,
                target=target_name,
            )

            retry_increased = increase_retry(source_folder, retry_max, retry_delay)
            if retry_increased:
                lock_file.unlink()
            else:
                logger.info(f"Max retries reached, moving to {error_folder}")
                monitor.send_task_event(task_event.SUSPEND, task_content.id, 0, target_name, "Max retries reached")
                _move_sent_directory(task_content.id, source_folder, error_folder)
                monitor.send_task_event(task_event.MOVE, task_content.id, 0, str(error_folder), "Moved to error folder")
                monitor.send_event(m_events.PROCESSING, severity.ERROR, f"Series suspended after reaching max retries")
                _trigger_notification(task_content, mercure_events.ERROR)

        logger.info(f"Done with dispatching folder {source_folder}")
    else:
        pass
        # logger.warning(f"Folder {source_folder} is *not* ready for sending")


def _move_sent_directory(task_id, source_folder, destination_folder) -> None:
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
            (Path(target_folder) / mercure_names.PROCESSING).unlink()
        else:
            logger.debug(f"Moving {source_folder} to {destination_folder / source_folder.name}")
            shutil.move(source_folder, destination_folder / source_folder.name)
            (destination_folder / source_folder.name / mercure_names.PROCESSING).unlink()
    except:
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
        notification.trigger_notification_for_rule(current_rule, task.id, event, notification.get_task_custom_notification(task), task, request_do_send)
