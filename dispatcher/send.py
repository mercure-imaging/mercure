import json
import logging
import shlex
import shutil
import sys
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run

import daiquiri
from pydicom import dcmread

from common.helper import is_ready_for_sending

logger = daiquiri.getLogger("send")


def _read_destination(folder):
    destination_file = Path(folder) / "destination.json"
    if destination_file.exists():
        with open(destination_file, "r") as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"File destination.json not found in folder {folder}")


def _create_command(folder):
    destination = _read_destination(folder)
    destination_ip = destination["destination_ip"]
    destination_aetitle = destination["destination_aetitle"]
    destination_port = destination["destination_port"]
    dcmsend_status_file = Path(folder) / "sent.txt"
    command = f"dcmsend {destination_ip} {destination_port} +sd {folder} \
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"
    return command


def execute(source_folder, success_folder, error_folder):
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
    result = execute(sys.argv[1], sys.argv[2], sys.argv[3])
    sys.exit(result)
