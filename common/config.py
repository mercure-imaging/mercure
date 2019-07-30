import json
import os
from pathlib import Path


configuration_timestamp = 0
configuration_filename  = "config.json"

hermes_defaults = {
    'incoming_folder'          : './incoming',
    'outgoing_folder'          : './outgoing',
    'router_scan_interval'     :  1,
    'dispatcher_scan_interval' :  1,
    'series_complete_trigger'  : 60,
    'graphite_ip'              : '',
    'graphite_port'            : 2003
}

hermes = {}


def read_config():
    global hermes
    global configuration_timestamp    
    configuration_file = Path(configuration_filename)

    # Check for existence of lock file
    lock_file=Path(configuration_file.stem + '.lock')
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

        print("Reading configuration from: ", configuration_filename)

        with open(configuration_file, "r") as json_file:
            loaded_config=json.load(json_file)
            # Reset configuration to default values (to ensure all needed
            # keys are present in the configuration)
            hermes=hermes_defaults
            # Now merge with values loaded from configuration file
            hermes.update(loaded_config)

            print("")
            print("Active configuration: ")
            print(json.dumps(hermes, indent=4))
            print("")
            configuration_timestamp=timestamp
            return hermes
    else:
        raise FileNotFoundError(f"Configuration file not fould: {configuration_file}")
