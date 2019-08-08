import json
import logging
import os
from pathlib import Path

import daiquiri

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("config")

configuration_timestamp = 0
configuration_filename  = os.path.realpath(os.path.dirname(os.path.realpath(__file__))+'/../configuration/hermes.json')

hermes_defaults = {
    'appliance_name'           : 'Hermes Router',
    'incoming_folder'          : './incoming',
    'outgoing_folder'          : './outgoing',
    'success_folder'           : './success',
    'error_folder'             : './error',
    'discard_folder'           : './discard',
    'router_scan_interval'     :      1, # in seconds
    'dispatcher_scan_interval' :      1, # in seconds
    'cleaner_scan_interval'    :     10, # in seconds
    'retention'                : 604800, # in seconds (7 days)
    'series_complete_trigger'  :     60, # in seconds
    'graphite_ip'              :     '',
    'graphite_port'            :   2003,
    "targets"                  :     {},
    "rules"                    :     {}
}

hermes = {}


def read_config():
    global hermes
    global configuration_timestamp
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file=Path(configuration_file.parent/configuration_file.stem).with_suffix(".lock")

    if lock_file.exists():
        raise ResourceWarning(f"Configuration file locked: {lock_file}")

    if configuration_file.exists():
        # Get the modification date/time of the configuration file
        stat = os.stat(configuration_filename)
        try:
            timestamp=stat.st_mtime
        except AttributeError:
            timestamp=0

        # Check if the configuration file is newer than the version
        # loaded into memory. If not, return
        if timestamp <= configuration_timestamp:
            return hermes

        logger.info("Reading configuration from: {configuration_filename}")

        with open(configuration_file, "r") as json_file:
            loaded_config=json.load(json_file)
            # Reset configuration to default values (to ensure all needed
            # keys are present in the configuration)
            hermes=hermes_defaults
            # Now merge with values loaded from configuration file
            hermes.update(loaded_config)

            # TODO: Check configuration for errors (esp targets and rules)

            # Check if directories exist
            if not checkFolders():
                raise FileNotFoundError("Configured folders missing")

            logger.info("")
            logger.info("Active configuration: ")
            logger.info(json.dumps(hermes, indent=4))
            logger.info("")
            configuration_timestamp=timestamp
            return hermes
    else:
        raise FileNotFoundError(f"Configuration file not fould: {configuration_file}")


def save_config():
    global configuration_timestamp
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file=Path(configuration_file.parent/configuration_file.stem).with_suffix(".lock")

    if lock_file.exists():
        raise ResourceWarning(f"Configuration file locked: {lock_file}")

    with open(configuration_file, "w") as json_file:
        json.dump(hermes,json_file, indent=4)

    try:
        stat = os.stat(configuration_file)
        configuration_timestamp=stat.st_mtime
    except AttributeError:
        configuration_timestamp=0

    logger.info("Stored configuration into: ", configuration_file)


def checkFolders():
    for entry in ['incoming_folder','outgoing_folder','success_folder','error_folder','discard_folder']:
        if not Path(hermes[entry]).exists():
            logger.info("ERROR: Folder not found ",hermes[entry])
            return False
    return True
