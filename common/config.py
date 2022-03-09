"""
config.py
=========
mercure's configuration management, used by various mercure modules 
"""

# Standard python includes
import json
import logging
import os, sys
from pathlib import Path
from typing_extensions import Literal
import daiquiri
from typing import Dict, cast
import re

# App-specific includes
import common.monitor as monitor
import common.helper as helper
from common.constants import mercure_names
from common.types import Config

# Create local logger instance
logger = daiquiri.getLogger("config")

configuration_timestamp: float = 0
configuration_filename = (
    os.getenv("MERCURE_CONFIG_FOLDER")
    or "/opt/mercure/config"
) + "/mercure.json"

mercure_defaults = {
    "appliance_name": "master",
    "port": 11112,
    "accept_compressed_images": "False",
    "incoming_folder": "/opt/mercure/data/incoming",
    "studies_folder": "/opt/mercure/data/studies",
    "outgoing_folder": "/opt/mercure/data/outgoing",
    "success_folder": "/opt/mercure/data/success",
    "error_folder": "/opt/mercure/data/error",
    "discard_folder": "/opt/mercure/data/discard",
    "processing_folder": "/opt/mercure/data/processing",
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
    "process_runner": "docker",
    "targets": {},
    "rules": {},
    "modules": {},
}

mercure: Config


def get_loglevel() -> int:
    """Returns the logging level that should be used for printing messages."""
    if any(re.findall(r"pytest|py.test", sys.argv[0])):
        return logging.DEBUG

    level = os.getenv("MERCURE_LOG_LEVEL", "info").lower()
    if level == "error":
        return logging.ERROR
    if level == "info":
        return logging.INFO
    if level == "debug":
        return logging.DEBUG
    return logging.INFO


def get_runner() -> str:
    """Returns the name of the mechanism that is used for running mercure in the current installation (systemd, docker, nomad)."""
    return os.getenv("MERCURE_RUNNER", "systemd")


def get_logformat() -> str:
    """Returns the format that should be used for log messages. Includes the time for docker and nomad, but not for systemd as journalctl 
    already outputs the time of the log events."""
    if get_runner() == "systemd":
        return "%(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s"
    else:
        return "%(asctime)s %(color)s%(levelname)-8.8s " "%(name)s: %(message)s%(color_stop)s"


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
            merged: Dict = {**mercure_defaults, **loaded_config}
            mercure = Config(**merged)

            # TODO: Check configuration for errors (esp targets and rules)

            # Check if directories exist
            if not check_folders():
                raise FileNotFoundError("Configured folders missing")

            # logger.info("")
            # logger.info("Active configuration: ")
            # logger.info(json.dumps(mercure, indent=4))
            # logger.info("")

            configuration_timestamp = timestamp
            monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.INFO, "Configuration updated")
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
        json.dump(mercure.dict(), json_file, indent=4)

    try:
        stat = os.stat(configuration_file)
        configuration_timestamp = stat.st_mtime
    except AttributeError:
        configuration_timestamp = 0

    monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.INFO, "Saved new configuration.")
    logger.info(f"Stored configuration into: {configuration_file}")

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        error_message = f"Unable to remove lock file {lock_file}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
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

    monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.INFO, "Wrote configuration file.")
    logger.info(f"Wrote configuration into: {configuration_file}")

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        error_message = f"Unable to remove lock file {lock_file}"
        logger.error(error_message)
        monitor.send_event(monitor.m_events.PROCESSING, monitor.severity.ERROR, error_message)
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
        if not Path(mercure.dict()[entry]).exists():
            error_message = f"Folder not found {mercure.dict()[entry]}"
            logger.error(error_message)
            monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.CRITICAL, error_message)
            return False
    return True
