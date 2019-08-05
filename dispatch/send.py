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
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run
import daiquiri

from common.helper import is_ready_for_sending

logger = daiquiri.getLogger("send")


def _read_target(folder):
    target_file = Path(folder) / "target.json"
    if target_file.exists():
        with open(target_file, "r") as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"File target.json not found in folder {folder}")


def _create_command(folder):
    target = _read_target(folder)
    target_ip = target["target_ip"]
    target_aet_target = target["target_aet_target"]
    target_aet_source = target["target_aet_source"]    
    target_port = target["target_port"]
    dcmsend_status_file = Path(folder) / "sent.txt"
    command = f"dcmsend {target_ip} {target_port} +sd {folder} \
            -aet {target_aet_source} -aec {target_aet_target} -nuc \
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"
    return command


def execute(source_folder, success_folder, error_folder):
    """ Execute the dcmsend command. """
    if is_ready_for_sending(source_folder):
        logger.info(f"Folder {source_folder} is ready for sending")
        # Create a .sending file to indicate that this folder is being sent,
        # otherwise the dispatcher would pick it up again
        lock_file = Path(source_folder) / ".sending"
        lock_file.touch()
        command = _create_command(source_folder)
        logger.debug(f"Running command {command}")
        try:
            result = run(shlex.split(command))
            result.check_returncode()
            lock_file.unlink()
            logger.info(
                f"Folder {source_folder} was sent successful, moving to {success_folder}"
            )
            shutil.move(source_folder, success_folder)
        except CalledProcessError:
            send_error_file = Path(source_folder / "send.error")
            lock_file.unlink()
    else:
        logger.warn(f"Folder {source_folder} is *not* ready for sending")


if __name__ == "__main__":
    result = 0
    execute(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit(result)
