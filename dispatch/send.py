"""
send.py
====================================
The file for sending the dicoms to
target destination.
"""
import json
import logging
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run

import daiquiri

from common.helper import is_ready_for_sending

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


def _read_target(folder):
    target_file = Path(folder) / "target.json"
    with open(target_file, "r") as f:
        return json.load(f)


def _create_command(folder):
    target = _read_target(folder)

    if not all(
        [key in target for key in ["target_ip", "target_port", "target_aet_target"]]
    ):
        raise KeyError(
            f"Mandatory key of ['target_ip', 'target_port', 'target_aet_target'] is missing in target.json = {target}"
        )
    target_ip = target["target_ip"]
    target_port = target["target_port"]
    target_aet_target = target["target_aet_target"]
    target_aet_source = target.get("target_aet_source", "")
    dcmsend_status_file = Path(folder) / "sent.txt"
    command = f"""dcmsend {target_ip} {target_port} +sd {folder}
            -aet {target_aet_source} -aec {target_aet_target} -nuc
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"""
    return command


def execute(source_folder, success_folder, error_folder):
    """
    Execute the dcmsend command. It will create a .lock file to indicate that
    the folder is being sent. This is to prevent double sending. If there
    happens any error the .lock file is deleted and an .error file is created.
    Folder with .error files are _not_ ready for sending.
    """
    if is_ready_for_sending(source_folder):
        logger.info(f"Folder {source_folder} is ready for sending")
        # Create a .sending file to indicate that this folder is being sent,
        # otherwise the dispatcher would pick it up again if the transfer is
        # still going on
        lock_file = Path(source_folder) / ".sending"
        lock_file.touch()
        command = _create_command(source_folder)
        logger.debug(f"Running command {command}")
        try:
            result = run(shlex.split(command), check=True)
            logger.info(
                f"Folder {source_folder} was sent successful, moving to {success_folder}"
            )
            lock_file.unlink()
            _move_sent_directory(success_folder, source_folder)
        except CalledProcessError as e:
            lock_file.unlink()
            dcmsend_error_message = DCMSEND_ERROR_CODES.get(e.returncode, None)
            logger.exception(
                f"Failed command:\n {command} \nbecause of {dcmsend_error_message}"
            )
            (Path(source_folder) / ".error").touch()

    else:
        logger.warn(f"Folder {source_folder} is *not* ready for sending")


def _move_sent_directory(success_folder, source_folder):
    """
    This check is needed if there is already a folder with the same name
    in the success folder (sent two time). Then a new directory is created
    with a timestamp as suffix.
    """
    if (success_folder / source_folder.name).exists():
        shutil.move(
            source_folder,
            success_folder / (source_folder.name + "_" + datetime.now().isoformat()),
            copy_function=shutil.copy2,
        )
    else:
        shutil.move(source_folder, str(success_folder))


if __name__ == "__main__":
    result = 0
    execute(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit(result)
