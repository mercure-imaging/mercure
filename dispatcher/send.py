import json
import logging
import shlex
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


def _read_study_instance(folder):
    dicoms = list(Path(folder).glob("*.dcm"))
    if len(dicoms):
        return dcmread(str(dicoms[0])).StudyInstanceUID
    else:
        raise FileNotFoundError(f"No *.dcm files could be found in folder {folder}")


def _create_command(folder):
    destination = _read_destination(folder)
    destination_ip = destination["destination_ip"]
    destination_aetitle = destination["destination_aetitle"]
    destination_port = destination["destination_port"]
    study_instance_uid = _read_study_instance(folder)
    dcmsend_status_file = Path(folder) / (study_instance_uid + ".txt")
    command = f"dcmsend {destination_ip} {destination_port} +sd {folder} \
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"
    return command


def execute(folder):
    if is_ready_for_sending(folder):
        logger.info(f"Folder {folder} is ready for sending")
        # Create a .sending file to indicate that this folder is being sent,
        # otherwise the dispatcher would pick it up again
        lock_file = (Path(folder) / ".sending")
        lock_file.touch()
        study_instance_uid = _read_study_instance(folder)
        command = _create_command(folder)
        logger.debug(f"Running command {command}")
        try:
            result = run(shlex.split(command))
            result.check_returncode()
            lock_file.unlink()
            logger.info(f"Folder {folder} was sent successful")
        except CalledProcessError:
            send_error_file = Path(folder / "send.error")
            lock_file.unlink()
    else:
        logger.warn(f"Folder {folder} is *not* ready for sending")


if __name__ == "__main__":
    result = execute(sys.argv[1])
    sys.exit(result)
