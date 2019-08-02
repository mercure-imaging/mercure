import os
import sys
from pathlib import Path
import time
import uuid
import json
import shutil

# App-specific includes
import common.helper as helper
import common.config as config


class FileLock:     
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
    lock_file=Path(config.hermes['incoming_folder'] + '/' + str(series_UID) + '.lock')

    if lock_file.exists():
        # Series is locked, so another instance might be working on it
        return

    try:
        lock=FileLock(lock_file)
    except:
        # Can't create lock file, so something must be seriously wrong
        print('ERROR: Unable to create lock file ',lock_file)
        return 

    print('Now processing series ',series_UID)

    fileList = []
    
    seriesPrefix=series_UID+"#"

    for entry in os.scandir(config.hermes['incoming_folder']):
            if entry.name.endswith(".tags") and entry.name.startswith(seriesPrefix) and not entry.is_dir():
                stemName=entry.name[:-5]
                fileList.append(stemName)

    print("DICOMs found:",len(fileList))    

    tagsMasterFile=Path(config.hermes['incoming_folder'] + '/' + fileList[0] + ".tags")
    if not tagsMasterFile.exists():
        print('ERROR: Missing file!',tagsMasterFile.name)
        return

    try:
        with open(tagsMasterFile, "r") as json_file:
            tagsList=json.load(json_file)    
    except Exception as e: 
        print(e)
        print("ERROR: Invalid tag information of series ",series_UID)    
        return

    # Now decide to which targets the series should be sent to
    transfer_targets = get_routing_targets(tagsList)    

    if len(transfer_targets)==0:
        push_series_discard(fileList)
    else:
        push_series_outgoing(fileList,transfer_targets)

    try:
        lock.free()
    except:
        # Can't delete lock file, so something must be seriously wrong
        print('ERROR: Unable to remove lock file ',lock_file)
        return 


def get_routing_targets(tagList):
    selected_targets = ['A','B','C']

    # TODO: Evaluate the routing rules
    return selected_targets


def push_series_discard(fileList):
    sourceFolder=config.hermes['incoming_folder'] + '/' 
    targetFolder=config.hermes['discard_folder'] + '/' 

    for entry in fileList:
        try:
            shutil.move(sourceFolder+entry+'.dcm',targetFolder+entry+'.dcm')
            shutil.move(sourceFolder+entry+'.tags',targetFolder+entry+'.tags')
        except Exception as e: 
            print(e)    
            print('ERROR: Problem during discarding file ',entry)    
            # TODO: Send alert


def push_series_outgoing(fileList,transfer_targets):
    sourceFolder=config.hermes['incoming_folder'] + '/'   

    for target in transfer_targets:      
        # Determine if the files should be copied or moved. For the last
        # target, the files should be moved to reduce IO overhead
        move_operation=False
        if target==transfer_targets[-1]:
            move_operation=True
        
        folder_name=config.hermes['outgoing_folder'] + '/' + uuid.uuid1()
        
        try:
            os.mkdir(folder_name)
        except Exception as e: 
            print(e)    
            print('ERROR: Unable to create outgoing folder ', folder_name)
            # TODO: Send alert            
            return

        if not Path(folder_name).exists():
            print('ERROR: Creating folder not possible ', folder_name)
            # TODO: Send alert            
            return

        try:
            lock_file=Path(folder_name + '/lock')
            lock=FileLock(lock_file)
        except:
            # Can't create lock file, so something must be seriously wrong
            print('ERROR: Unable to create lock file ',lock_file)
            return         
        
        if move_operation:
            operation=shutil.move
        else:
            operation=shutil.copy

        targetFolder=folder_name+"/"
        for entry in fileList:
            try:
                operation(sourceFolder+entry+'.dcm',targetFolder+entry+'.dcm')
                operation(sourceFolder+entry+'.tags',targetFolder+entry+'.tags')
            except Exception as e: 
                print(e)    
                print('ERROR: Problem during pusing file to outgoing ',entry)    
                # TODO: Send alert

        # TODO: Generate destination file destination.json
        destination_json = {}
        destination_json["destination_ip"]        ="TODO"
        destination_json["destination_port"]      ="TODO"                        
        destination_json["destination_aet_target"]="TODO"
        destination_json["destination_aec_source"]="TODO"
        destination_json["destination_name"]      ="TODO"

        destination_filename = targetFolder+"destination.json"

        try:
            with open(destination_filename, 'w') as destination_file:
                json.dump(destination_json, destination_file)            
        except:
            pass

        try:
            lock.free()
        except:
            # Can't delete lock file, so something must be seriously wrong
            print('ERROR: Unable to remove lock file ',lock_file)
            return 


