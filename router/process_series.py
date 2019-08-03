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
    selected_targets = {}

    for current_rule in config.hermes["rules"]:
        try:
            if config.hermes["rules"][current_rule].get("disabled","False")=="True":
                continue
            if current_rule in selected_targets:
                continue
            if parse_rule(config.hermes["rules"][current_rule].get("rule","False"),tagList):
                target=config.hermes["rules"][current_rule].get("target","")
                if target:
                    selected_targets[target]=current_rule
        except:
            print("ERROR: Invalid rule found: ", current_rule) 
            continue
        
    print("Selected routing:")
    print(selected_targets)

    #selected_targets['aidoc']='RuleA'
    #selected_targets['B']='RuleB'

    return selected_targets


def push_series_discard(fileList):
    source_folder=config.hermes['incoming_folder'] + '/' 
    target_folder=config.hermes['discard_folder'] + '/' 

    for entry in fileList:
        try:
            shutil.move(source_folder+entry+'.dcm',target_folder+entry+'.dcm')
            shutil.move(source_folder+entry+'.tags',target_folder+entry+'.tags')
        except Exception as e: 
            print(e)    
            print('ERROR: Problem during discarding file ',entry)    
            # TODO: Send alert


def push_series_outgoing(fileList,transfer_targets):
    source_folder=config.hermes['incoming_folder'] + '/'   

    total_targets=len(transfer_targets)
    current_target=0

    for target in transfer_targets:      

        current_target=current_target+1

        if not target in config.hermes["destinations"]:
            print("ERROR: Invalid target selected ",target)
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

        # Generate destination file destination.json
        destination_filename = target_folder + "destination.json"
        destination_json = {}

        destination_json["destination_ip"]        =config.hermes["destinations"][target]["ip"]
        destination_json["destination_port"]      =config.hermes["destinations"][target]["port"]                      
        destination_json["destination_aet_target"]=config.hermes["destinations"][target].get("aet_target","ANY-SCP")
        destination_json["destination_aec_source"]=config.hermes["destinations"][target].get("aet_source","HERMES")
        destination_json["destination_name"]      =target
        destination_json["applied_rule"]          =transfer_targets[target]

        try:
            with open(destination_filename, 'w') as destination_file:
                json.dump(destination_json, destination_file)            
        except:
            print("ERROR: Unable to create destination file " + destination_filename)
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
                print(e)    
                print('ERROR: Problem during pusing file to outgoing ',entry)    
                # TODO: Send alert

        try:
            lock.free()
        except:
            # Can't delete lock file, so something must be seriously wrong
            print('ERROR: Unable to remove lock file ',lock_file)
            return 


safe_eval_cmds={"float": float, "int": int, "str": str}

def parse_rule(rule,tags):
    try:
        print("Rule: ",rule)
        while len(rule)>0:
            opening=rule.find("@")
            if opening<0:
                break
            closing=rule.find("@",opening+1)
            if closing<0:
                break
            tagstring=rule[opening+1:closing]
            if tagstring in tags:
                tagvalue=tags[tagstring]    
            else:
                tagvalue="MissingTag"
            rule=rule.replace("@"+tagstring+"@","'"+tagvalue+"'")

        print("Evaluated: ",rule)
        result=eval(rule,{"__builtins__": {}},safe_eval_cmds)
        print("Result: ",result)
        return result
    except:
        print("WARNING: Invalid rule expression ",'"'+rule+'"')
        return False



#if __name__ == "__main__":
#    result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
#    print(result)
#    sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"
