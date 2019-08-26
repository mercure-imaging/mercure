"""
send.py
====================================
The functions for sending DICOM series
to target destinations.
"""

import shutil
from datetime import datetime
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run

import daiquiri

from common.helper import is_ready_for_sending
from common.monitor import s_events, send_series_event

logger = daiquiri.getLogger("send")

DCMSEND_ERROR_CODES = {
    1: "EXITCODE_COMMANDLINE_SYNTAX_ERROR",
    21: "EXITCODE_NO_INPUT_FILES",
    22: "EXITCODE_INVALID_INPUT_FILE",
    23: "EXITCODE_NO_VALID_INPUT_FILES",
    43: "EXITCODE_CANNOT_WRITE_REPORT_FILE",
    60: "EXITCODE_CANNOT_INITIALIZE_NETWORK",
    61: "EXITCODE_CANNOT_NEGOTIATE_ASSOCIATION",
    62: "EXITCODE_CANNOT_SEND_REQUEST",
    65: "EXITCODE_CANNOT_ADD_PRESENTATION_CONTEXT",
}


def _create_command(target, folder):
    target_ip = target["target_ip"]
    target_port = target["target_port"]
    target_aet_target = target["target_aet_target"]
    target_aet_source = target.get("target_aet_source", "")
    dcmsend_status_file = Path(folder) / "sent.txt"
    command = f"""dcmsend {target_ip} {target_port} +sd {folder}
            -aet {target_aet_source} -aec {target_aet_target} -nuc
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"""
    return command, target


def execute(source_folder, success_folder, error_folder):
    """
    Execute the dcmsend command. It will create a .lock file to indicate that
    the folder is being sent. This is to prevent double sending. If there
    happens any error the .lock file is deleted and an .error file is created.
    Folder with .error files are _not_ ready for sending.
    """
    ready, target = is_ready_for_sending(source_folder)
    if ready:
        logger.info(f"Folder {source_folder} is ready for sending")
        # Create a .sending file to indicate that this folder is being sent,
        # otherwise the dispatcher would pick it up again if the transfer is
        # still going on
        lock_file = Path(source_folder) / ".sending"
        lock_file.touch()
        command, target = _create_command(target, source_folder)
        logger.debug(f"Running command {command}")
        try:
            run(split(command), check=True)
            logger.info(
                f"Folder {source_folder} successfully sent, moving to {success_folder}"
            )
            # Send bookkeeper notification
            file_count = len(list(Path(source_folder).glob("*.dcm")))
            send_series_event(
                s_events.DISPATCH,
                target["series_uid"],
                file_count,
                target["target_name"],
                "",
            )
            _move_sent_directory(success_folder, source_folder)
            # Move was successful, so lockfile .sending can be deleted
            lock_file.unlink()
        except CalledProcessError as e:
            dcmsend_error_message = DCMSEND_ERROR_CODES.get(e.returncode, None)
            logger.exception(
                f"Failed command:\n {command} \nbecause of {dcmsend_error_message}"
            )
            (Path(source_folder) / ".error").touch()
            send_series_event(
                s_events.ERROR,
                target["series_uid"],
                file_count,
                target["target_name"],
                dcmsend_error_message,
            )
            lock_file.unlink()
    else:
        logger.warn(f"Folder {source_folder} is *not* ready for sending")


def _move_sent_directory(success_folder, source_folder):
    """
    This check is needed if there is already a folder with the same name
    in the success folder. If so a new directory is create with a timestamp
    as suffix.
    """
    if (success_folder / source_folder.name).exists():
        shutil.move(
            source_folder,
            success_folder / (source_folder.name + "_" + datetime.now().isoformat()),
            copy_function=shutil.copy2,
        )
    else:
        shutil.move(str(source_folder), str(success_folder))
