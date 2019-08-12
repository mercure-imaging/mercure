import os
import sys
from pathlib import Path
import time
import uuid
import json
import shutil
import logging

import daiquiri

# App-specific includes
import common.helper as helper
import common.config as config
import common.rule_evaluation as rule_evaluation

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("process_series")


class FileLock:
    """Helper class that implements a file lock. The lock file will be removed also from the destructor so that
       no spurious lock files remain if exceptions are raised."""
    def __init__(self, path_for_lockfile):
        self.lockCreated=True
        self.lockfile=path_for_lockfile
        self.lockfile.touch()

    # Destructor to ensure that the lock file gets deleted
    # if the calling function is left somewhere as result
    # of an unhandled exception
    def __del__(self):
        self.free()

    def free(self):
        if self.lockCreated:
            self.lockfile.unlink()
            self.lockCreated=False


def process_series(series_UID):
    """Processes the series with the given series UID from the incoming folder."""
    lock_file=Path(config.hermes['incoming_folder'] + '/' + str(series_UID) + '.lock')

    if lock_file.exists():
        # Series is locked, so another instance might be working on it
        return

    try:
        lock=FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f'ERROR: Unable to create lock file {lock_file}')
        return

    logger.info(f'Processing series {series_UID}')

    fileList = []
    seriesPrefix=series_UID+"#"

    for entry in os.scandir(config.hermes['incoming_folder']):
            if entry.name.endswith(".tags") and entry.name.startswith(seriesPrefix) and not entry.is_dir():
                stemName=entry.name[:-5]
                fileList.append(stemName)

    logger.info("DICOMs found: {len(fileList)}")

    tagsMasterFile=Path(config.hermes['incoming_folder'] + '/' + fileList[0] + ".tags")
    if not tagsMasterFile.exists():
        logger.error(f'ERROR: Missing file! {tagsMasterFile.name}')
        return

    try:
        with open(tagsMasterFile, "r") as json_file:
            tagsList=json.load(json_file)
    except Exception as e:
        logger.error(e)
        logger.error(f"ERROR: Invalid tag information of series {series_UID}")
        return

    # Now decide to which targets the series should be sent to
    transfer_targets = get_routing_targets(tagsList)

    if len(transfer_targets)==0:
        push_series_discard(fileList,series_UID)
    else:
        push_series_outgoing(fileList,series_UID,transfer_targets)

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        logger.error(f'ERROR: Unable to remove lock file {lock_file}')
        return


def get_routing_targets(tagList):
    selected_targets = {}

    for current_rule in config.hermes["rules"]:
        try:
            if config.hermes["rules"][current_rule].get("disabled","False")=="True":
                continue
            if current_rule in selected_targets:
                continue
            if rule_evaluation.parse_rule(config.hermes["rules"][current_rule].get("rule","False"),tagList):
                target=config.hermes["rules"][current_rule].get("target","")
                if target:
                    selected_targets[target]=current_rule
        except Exception as e:
            logger.error(e)
            logger.error(f"ERROR: Invalid rule found: {current_rule}")
            continue

    logger.info("Selected routing:")
    logger.info(selected_targets)
    return selected_targets


def push_series_discard(fileList,series_UID):
    source_folder=config.hermes['incoming_folder'] + '/'
    target_folder=config.hermes['discard_folder'] + '/'

    lock_file=Path(config.hermes['discard_folder'] + '/' + str(series_UID) + '.lock')
    if lock_file.exists():
        # Lock file exists in discard folder. This should normally not happen. Send alert.
        logger.error(f'ERROR: Stale lock file found in discard folder {lock_file}')
        return

    try:
        lock=FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f'ERROR: Unable to create lock file {lock_file}')
        return

    for entry in fileList:
        try:
            shutil.move(source_folder+entry+'.dcm',target_folder+entry+'.dcm')
            shutil.move(source_folder+entry+'.tags',target_folder+entry+'.tags')
        except Exception as e:
            logger.error(e)
            logger.error(f'ERROR: Problem during discarding file {entry}')
            # TODO: Send alert
    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        logger.error(f'ERROR: Unable to remove lock file {lock_file}')
        return


def push_series_outgoing(fileList,series_UID,transfer_targets):
    source_folder=config.hermes['incoming_folder'] + '/'

    total_targets=len(transfer_targets)
    current_target=0

    for target in transfer_targets:

        current_target=current_target+1

        if not target in config.hermes["targets"]:
            logger.error(f"ERROR: Invalid target selected {target}")
            continue

        # Determine if the files should be copied or moved. For the last
        # target, the files should be moved to reduce IO overhead
        move_operation=False
        if current_target==total_targets:
            move_operation=True

        folder_name=config.hermes['outgoing_folder'] + '/' + str(uuid.uuid1())
        target_folder=folder_name+"/"

        try:
            os.mkdir(folder_name)
        except Exception as e:
            logger.error(e)
            logger.error(f'ERROR: Unable to create outgoing folder {folder_name}')
            # TODO: Send alert
            return

        if not Path(folder_name).exists():
            logger.error(f'ERROR: Creating folder not possible {folder_name}')
            # TODO: Send alert
            return

        try:
            lock_file=Path(folder_name + '/lock')
            lock=FileLock(lock_file)
        except:
            # Can't create lock file, so something must be seriously wrong
            logger.error(f'ERROR: Unable to create lock file {lock_file}')
            return

        # Generate target file target.json
        target_filename = target_folder + "target.json"
        target_json = {}

        target_json["target_ip"]        =config.hermes["targets"][target]["ip"]
        target_json["target_port"]      =config.hermes["targets"][target]["port"]
        target_json["target_aet_target"]=config.hermes["targets"][target].get("aet_target","ANY-SCP")
        target_json["target_aec_source"]=config.hermes["targets"][target].get("aet_source","HERMES")
        target_json["target_name"]      =target
        target_json["applied_rule"]     =transfer_targets[target]

        try:
            with open(target_filename, 'w') as target_file:
                json.dump(target_json, target_file)
        except:
            logger.error(f"ERROR: Unable to create target file {target_filename}")
            continue

        if move_operation:
            operation=shutil.move
        else:
            operation=shutil.copy

        for entry in fileList:
            try:
                operation(source_folder+entry+'.dcm',target_folder+entry+'.dcm')
                operation(source_folder+entry+'.tags',target_folder+entry+'.tags')
            except Exception as e:
                logger.error(e)
                logger.error(f'ERROR: Problem during pusing file to outgoing {entry}')
                # TODO: Send alert

        try:
            lock.free()
        except:
            # Can't delete lock file, so something must be seriously wrong
            logger.error(f'ERROR: Unable to remove lock file {lock_file}')
            return
