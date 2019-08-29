import json
import os
from pathlib import Path
import common.monitor as monitor
import daiquiri

logger = daiquiri.getLogger("config")

configuration_timestamp = 0
configuration_filename  = os.path.realpath(os.path.dirname(os.path.realpath(__file__))+'/../configuration/hermes.json')

hermes_defaults = {
    'appliance_name'           : 'Hermes Router',
    'incoming_folder'          :    './incoming',
    'outgoing_folder'          :    './outgoing',
    'success_folder'           :     './success',
    'error_folder'             :       './error',
    'discard_folder'           :     './discard',
    'router_scan_interval'     :               1, # in seconds
    'dispatcher_scan_interval' :               1, # in seconds
    'cleaner_scan_interval'    :              10, # in seconds
    'retention'                :          432000, # in seconds (5 days)
    'retry_delay'              :             900, # in seconds (15 min)
    'retry_max'                :               5,
    'series_complete_trigger'  :              60, # in seconds
    'graphite_ip'              :              '',
    'graphite_port'            :            2003,
    'bookkeeper'               :  '0.0.0.0:8080',
    'targets'                  :              {},
    'rules'                    :              {}
}

hermes = {}


def read_config():
    """Reads the configuration settings (rules, targets, general settings) from the configuration file. The configuration will
       only be updated if the file has changed compared the the last function call. If the configuration file is locked by
       another process, an exception will be raised."""
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

        logger.info(f"Reading configuration from: {configuration_filename}")

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

            #logger.info("")
            #logger.info("Active configuration: ")
            #logger.info(json.dumps(hermes, indent=4))
            #logger.info("")

            configuration_timestamp=timestamp
            monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.INFO, "Configuration updated")
            return hermes
    else:
        raise FileNotFoundError(f"Configuration file not found: {configuration_file}")


def save_config():
    """Saves the current configuration in a file on the disk. Raises an exception if the file has
       been locked by another process."""
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

    monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.INFO, "Saved new configuration.")
    logger.info(f"Stored configuration into: {configuration_file}")


def checkFolders():
    """Checks if all required folders for handling the DICOM files exist."""
    for entry in ['incoming_folder','outgoing_folder','success_folder','error_folder','discard_folder']:
        if not Path(hermes[entry]).exists():
            logger.error(f"Folder not found {hermes[entry]}")
            monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.CRITICAL, "Folders are missing")
            return False
    return True
