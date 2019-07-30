import json
import logging
import shlex
import sys
from pathlib import Path
from shlex import split
from subprocess import run

import daiquiri

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("send")


def _is_ready(folder):
    """ 
    No lock file should be in sending folder, if there is one copy/move is 
    not done yet. Also at least some dicom files should be there for sending.
    """
    return (
        len(list(Path(folder).glob("*.lock"))) == 0
        and len(list(Path(folder).glob("*.dcm"))) > 0
    )


def _read_destination(folder):
    destination_file = Path(folder) / "destination.json"
    if destination_file.exists():
        with open(destination_file, "r") as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"File destination.json not found in folder {folder}")


def _read_study_instance(folder):
    tags = list(Path(folder).glob("*.tags"))
    if len(tags):
        return tags[0].name.split("#")[0]
    else:
        raise FileNotFoundError(f"No *.dcm files could be found in folder {folder}")


def execute(folder):
    if _is_ready(folder):
        logger.info(f"Folder {folder} is ready for sending")
        study_instance_uid = _read_study_instance(folder)
        destination = _read_destination(folder)
        destination_ip = destination["destination_ip"]
        destination_aetitle = destination["destination_aetitle"]
        destination_port = destination["destination_port"]
        dcmsend_status_file = Path(folder) / (study_instance_uid + ".txt")
        command = f"dcmsend {destination_ip} {destination_port} +sd {folder} \
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"
        logger.debug(f"Running command {command}")
        result = run(shlex.split(command))
        result.check_returncode()
        logger.info(f"Folder {folder} was sent successful")
        return result.returncode
    else:
        logger.warn(f"Folder {folder} is *not* ready for sending")


if __name__ == "__main__":
    result = execute(sys.argv[1])
    sys.exit(result)
