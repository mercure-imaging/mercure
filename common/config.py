"""
config.py
=========
mercure's configuration management, used by various mercure modules 
"""

# Standard python includes
import json
import os
from pathlib import Path
from typing_extensions import Literal
import daiquiri
from typing import cast

# App-specific includes
import common.monitor as monitor
import common.helper as helper
from common.constants import mercure_names, mercure_folders
from common.types import Config

# Create local logger instance
logger = daiquiri.getLogger("config")

configuration_timestamp: float = 0
configuration_filename = os.path.realpath(
    os.path.dirname(os.path.realpath(__file__)) + "/../configuration/mercure.json"
)

mercure_defaults = {
    "appliance_name": "master",
    "port": 104,
    "incoming_folder": "./incoming",
    "studies_folder": "./studies",
    "outgoing_folder": "./outgoing",
    "success_folder": "./success",
    "error_folder": "./error",
    "discard_folder": "./discard",
    "processing_folder": "./processing",
    "router_scan_interval": 1,  # in seconds
    "dispatcher_scan_interval": 1,  # in seconds
    "cleaner_scan_interval": 60,  # in seconds
    "retention": 259200,  # in seconds (3 days)
    "retry_delay": 900,  # in seconds (15 min)
    "retry_max": 5,
    "series_complete_trigger": 60,  # in seconds
    "study_complete_trigger": 900,  # in seconds
    "study_forcecomplete_trigger": 5400,  # in seconds
    "graphite_ip": "",
    "graphite_port": 2003,
    "bookkeeper": "0.0.0.0:8080",
    "offpeak_start": "22:00",
    "offpeak_end": "06:00",
    "targets": {},
    "rules": {},
    "modules": {},
}

mercure: Config


def read_config() -> Config:
    """Reads the configuration settings (rules, targets, general settings) from the configuration file. The configuration will
    only be updated if the file has changed compared the the last function call. If the configuration file is locked by
    another process, an exception will be raised."""
    global mercure
    global configuration_timestamp
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file = Path(configuration_file.parent / configuration_file.stem).with_suffix(mercure_names.LOCK)

    if lock_file.exists():
        raise ResourceWarning(f"Configuration file locked: {lock_file}")

    if configuration_file.exists():
        # Get the modification date/time of the configuration file
        stat = os.stat(configuration_filename)
        try:
            timestamp = stat.st_mtime
        except AttributeError:
            timestamp = 0

        # Check if the configuration file is newer than the version
        # loaded into memory. If not, return
        if timestamp <= configuration_timestamp:
            return mercure

        logger.info(f"Reading configuration from: {configuration_filename}")

        with open(configuration_file, "r") as json_file:
            loaded_config = json.load(json_file)
            # Reset configuration to default values (to ensure all needed
            # keys are present in the configuration)
            mercure = cast(Config, mercure_defaults)
            # Now merge with values loaded from configuration file
            mercure.update(loaded_config)

            # TODO: Check configuration for errors (esp targets and rules)

            # Check if directories exist
            if not check_folders():
                raise FileNotFoundError("Configured folders missing")

            # logger.info("")
            # logger.info("Active configuration: ")
            # logger.info(json.dumps(mercure, indent=4))
            # logger.info("")

            configuration_timestamp = timestamp
            monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.INFO, "Configuration updated")
            return mercure
    else:
        raise FileNotFoundError(f"Configuration file not found: {configuration_file}")


def save_config() -> None:
    """Saves the current configuration in a file on the disk. Raises an exception if the file has
    been locked by another process."""
    global configuration_timestamp, mercure
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file = Path(configuration_file.parent / configuration_file.stem).with_suffix(mercure_names.LOCK)

    if lock_file.exists():
        raise ResourceWarning(f"Configuration file locked: {lock_file}")

    try:
        lock = helper.FileLock(lock_file)
    except:
        raise ResourceWarning(f"Unable to lock configuration file: {lock_file}")

    with open(configuration_file, "w") as json_file:
        json.dump(mercure, json_file, indent=4)

    try:
        stat = os.stat(configuration_file)
        configuration_timestamp = stat.st_mtime
    except AttributeError:
        configuration_timestamp = 0

    monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.INFO, "Saved new configuration.")
    logger.info(f"Stored configuration into: {configuration_file}")

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        logger.error(f"Unable to remove lock file {lock_file}")
        monitor.send_event(
            monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to remove lock file {lock_file}"
        )
        return


def write_configfile(json_content) -> None:
    """Rewrites the config file using the JSON data passed as argument. Used by the config editor of the webgui."""
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file = Path(configuration_file.parent / configuration_file.stem).with_suffix(mercure_names.LOCK)

    if lock_file.exists():
        raise ResourceWarning(f"Configuration file locked: {lock_file}")

    try:
        lock = helper.FileLock(lock_file)
    except:
        raise ResourceWarning(f"Unable to lock configuration file: {lock_file}")

    with open(configuration_file, "w") as json_file:
        json.dump(json_content, json_file, indent=4)

    monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.INFO, "Wrote configuration file.")
    logger.info(f"Wrote configuration into: {configuration_file}")

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        logger.error(f"Unable to remove lock file {lock_file}")
        monitor.send_event(
            monitor.h_events.PROCESSING, monitor.severity.ERROR, f"Unable to remove lock file {lock_file}"
        )
        return


def check_folders() -> bool:
    """Checks if all required folders for handling the DICOM files exist."""
    global mercure

    for entry in [
        "incoming_folder",
        "studies_folder",
        "outgoing_folder",
        "success_folder",
        "error_folder",
        "discard_folder",
        "processing_folder",
    ]:
        entry = cast(
            Literal[
                "incoming_folder",
                "studies_folder",
                "outgoing_folder",
                "success_folder",
                "error_folder",
                "discard_folder",
                "processing_folder",
            ],
            entry,
        )
        if not Path(mercure[entry]).exists():
            logger.error(f"Folder not found {mercure[entry]}")
            monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.CRITICAL, "Folders are missing")
            return False
    return True
