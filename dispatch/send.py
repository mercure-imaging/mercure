"""
send.py
=======
The functions for sending DICOM series
to target destinations.
"""
import shutil
import time
from datetime import datetime
from pathlib import Path
from shlex import split
from subprocess import CalledProcessError, run

import daiquiri

from common.monitor import s_events, send_series_event, send_event, h_events, severity
from dispatch.retry import increase_retry
from dispatch.status import is_ready_for_sending
from common.constants import mercure_names


logger = daiquiri.getLogger("send")

DCMSEND_ERROR_CODES = {
    1: "EXITCODE_COMMANDLINE_SYNTAX_ERROR",
    21: "EXITCODE_NO_INPUT_FILES",
    22: "EXITCODE_INVALID_INPUT_FILE",
    23: "EXITCODE_NO_VALID_INPUT_FILES",
    43: "EXITCODE_CANNOT_WRITE_REPORT_FILE",
    60: "EXITCODE_CANNOT_INITIALIZE_NETWORK",
    61: "EXITCODE_CANNOT_NEGOTIATE_ASSOCIATION",
    62: "EXITCODE_CANNOT_SEND_REQUEST",
    65: "EXITCODE_CANNOT_ADD_PRESENTATION_CONTEXT",
}


def _create_command(target_info, folder):
    """Composes the command for calling the dcmsend tool from DCMTK, which is used for sending out the DICOMS."""
    target_ip         = target_info.get("dispatch",{}).get("target_ip","")
    target_port       = target_info.get("dispatch",{}).get("target_port","")
    target_aet_target = target_info.get("dispatch",{}).get("target_aet_target","")
    target_aet_source = target_info.get("dispatch",{}).get("target_aet_source","")
    
    dcmsend_status_file = Path(folder) / mercure_names.SENDLOG

    command = f"""dcmsend {target_ip} {target_port} +sd {folder}
            -aet {target_aet_source} -aec {target_aet_target} -nuc
            +sp '*.dcm' -to 60 +crf {dcmsend_status_file}"""
    
    return command


def execute(
    source_folder: Path,
    success_folder: Path,
    error_folder: Path,
    retry_max,
    retry_delay,
):
    """
    Execute the dcmsend command. It will create a .sending file to indicate that
    the folder is being sent. This is to prevent double sending. If there
    happens any error the .lock file is deleted and an .error file is created.
    Folder with .error files are _not_ ready for sending.
    """
    target_info = is_ready_for_sending(source_folder)
    delay = target_info.get("next_retry_at", 0)

    if target_info and time.time() >= delay:
        logger.info(f"Folder {source_folder} is ready for sending")

        series_uid=target_info.get("series_uid", "series_uid-missing") 
        target_name=target_info.get("target_name", "target_name-missing")

        if (series_uid=="series_uid-missing") or (target_name=="target_name-missing"):
            send_event(h_events.PROCESSING, severity.WARNING, f"Missing information for folder {source_folder}")    

        # Create a .sending file to indicate that this folder is being sent,
        # otherwise the dispatcher would pick it up again if the transfer is
        # still going on
        lock_file = Path(source_folder) / mercure_names.PROCESSING
        try:
            lock_file.touch()            
        except:
            send_event(h_events.PROCESSING, severity.ERROR, f"Error sending {series_uid} to {target_name}")
            send_series_event(s_events.ERROR, series_uid, 0, target_name, "Unable to create lock file")
            logger.exception(f"Unable to create lock file {lock_file.name}")            
            return

        command = _create_command(target_info, source_folder)
        logger.debug(f"Running command {command}")
        try:
            run(split(command), check=True)
            logger.info(
                f"Folder {source_folder} successfully sent, moving to {success_folder}"
            )
            # Send bookkeeper notification
            file_count = len(list(Path(source_folder).glob(mercure_names.DCMFILTER)))
            send_series_event(
                s_events.DISPATCH,
                target_info.get("series_uid", "series_uid-missing"),
                file_count,
                target_info.get("target_name", "target_name-missing"),
                "",
            )
            _move_sent_directory(source_folder, success_folder)
            send_series_event(s_events.MOVE, series_uid, 0, success_folder, "")
        except CalledProcessError as e:
            dcmsend_error_message = DCMSEND_ERROR_CODES.get(e.returncode, None)
            logger.exception(
                f"Failed command:\n {command} \nbecause of {dcmsend_error_message}"
            )
            send_event(h_events.PROCESSING, severity.ERROR, f"Error sending {series_uid} to {target_name}")
            send_series_event(s_events.ERROR, series_uid, 0, target_name, dcmsend_error_message)
            retry_increased = increase_retry(source_folder, retry_max, retry_delay)
            if retry_increased:
                lock_file.unlink()
            else:
                logger.info(f"Max retries reached, moving to {error_folder}")
                send_series_event(s_events.SUSPEND, series_uid, 0, target_name, "Max retries reached")
                _move_sent_directory(source_folder, error_folder)
                send_series_event(s_events.MOVE, series_uid, 0, error_folder, "")
                send_event(h_events.PROCESSING, severity.ERROR, f"Series suspended after reaching max retries")
    else:
        pass
        #logger.warning(f"Folder {source_folder} is *not* ready for sending")


def _move_sent_directory(source_folder, destination_folder):
    """
    This check is needed if there is already a folder with the same name
    in the success folder. If so a new directory is create with a timestamp
    as suffix.
    """
    try:
        if (destination_folder / source_folder.name).exists():
            target_folder = destination_folder / (
                source_folder.name + "_" + datetime.now().isoformat()
            )
            logger.debug(f"Moving {source_folder} to {target_folder}")
            shutil.move(source_folder, target_folder, copy_function=shutil.copy2)
            (Path(target_folder) / mercure_names.PROCESSING).unlink()
        else:
            logger.debug(
                f"Moving {source_folder} to {destination_folder / source_folder.name}"
            )
            shutil.move(source_folder, destination_folder / source_folder.name)
            (destination_folder / source_folder.name / mercure_names.PROCESSING).unlink()
    except:
        logger.info(f"Error moving folder {source_folder} to {destination_folder}")        
        send_event(h_events.PROCESSING, severity.ERROR, f"Error moving {source_folder} to {destination_folder}")
