import subprocess
from pathlib import Path
import shlex


def _read_destination(folder):
    return Path(folder) / destination.json


def _read_tags(folder):
    return Path(folder).glob("*.tags")[0]

def exectue(folder):
    tags = _read_tags(folder)
    study_instance_uid = tags["study_instance_uid"]

    destination = _read_destination(folder)
    destination_ip = destination["destination_ip"]
    destination_aetitle = destination["destination_aetitle"]
    destination_port = destination["destination_port"]
    command = f"dcmsend +sd +crf {study_instance_uid}.txt {folder}/*.dcm"
    result = subprocess.run(shlex(command))
    result.check_returncode()
