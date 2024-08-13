import os
import sys
import json
import shutil
import argparse
from typing import Dict, List, Optional, Tuple
import pydicom
import requests
from pathlib import Path

VERSION = "1.0"

# Define the main tags to extract (you may need to adjust these based on your specific needs)
MAIN_TAGS = [
    'PatientName',
    'PatientID',
    'PatientBirthDate',
    'StudyDate',
    'StudyTime',
    'Modality',
    'StudyDescription',
    'InstitutionName',
    'ReferringPhysicianName',
    'StudyInstanceUID',
    'SeriesDescription',
    'ProtocolName',
    'SeriesNumber',
    'AcquisitionNumber',
    'InstanceNumber',
    'ImageType',
    'SOPClassUID'
]

def send_bookkeeper_post(filename, file_uid, series_uid, bookkeeper_address, bookkeeper_token)-> None:
    """Send a POST request to the bookkeeper."""
    if not bookkeeper_address:
        return

    url = f"http://{bookkeeper_address}/register-dicom"
    headers = {"Authorization": f"Token {bookkeeper_token}"}
    data = {
        "filename": filename,
        "file_uid": file_uid,
        "series_uid": series_uid
    }

    try:
        response = requests.post(url, headers=headers, data=data, timeout=3)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error sending request to bookkeeper: {e}")

def write_error_information(dcm_file: Path, error_string: str) -> None:
    """Write error information to a file."""
    err_folder = dcm_file.parent / "error"
    err_folder.mkdir(exist_ok=True)
    dcm_file = dcm_file.rename(dcm_file.parent / "error" / dcm_file.name)

    error_file = dcm_file.with_suffix('.error')
    lock_file = dcm_file.with_suffix('.error.lock')
    
    try:
        with lock_file.open('w') as _:
            pass

        with error_file.open('w') as f:
            f.write(f"ERROR: {error_string}\n")

        print(f"ERROR: {error_string}")
    except IOError as e:
        print(f"ERROR: Unable to write error file {error_file}: {e}")
    finally:
        if lock_file.exists():
            lock_file.unlink()

def read_extra_tags(dataset, extra_tags_file) -> List[Tuple[str,str]]:
    """Read extra tags from a file."""
    extra_tags = []
    if extra_tags_file.exists():
        with extra_tags_file.open('r') as f:
            for line in f:
                tag = line.strip()
                if tag in dataset:
                    extra_tags.append((tag, str(dataset[tag].value)))
    return extra_tags

def write_tags_file(dcm_file, original_file, dataset, main_tags, additional_tags, sender_address, sender_aet, receiver_aet) -> bool:
    """Write extracted tags to a JSON file."""
    tags_file = dcm_file.with_suffix('.tags')
    
    tags_data = {
        "SpecificCharacterSet": str(dataset.get("SpecificCharacterSet", "")),
        "SeriesInstanceUID": str(dataset.get("SeriesInstanceUID", "")),
        "SOPInstanceUID": str(dataset.get("SOPInstanceUID", "")),
        "SenderAddress": str(sender_address),
        "SenderAET": str(sender_aet),
        "ReceiverAET": str(receiver_aet),
    }

    for tag in main_tags:
        if tag in dataset:
            tags_data[tag] = str(dataset[tag].value)

    for tag, value in additional_tags:
        tags_data[tag] = value

    tags_data["Filename"] = str(original_file)

    try:
        with tags_file.open('w') as f:
            json.dump(tags_data, f, indent=2)
        return True
    except IOError as e:
        print(f"ERROR: Unable to write tag file {tags_file}: {e}")
        return False

def create_series_folder(path, series_uid) -> bool:
    """Create a folder for the series if it doesn't exist."""
    series_folder = path / series_uid
    try:
        series_folder.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as e:
        print(f"ERROR: Unable to create directory {series_folder}: {e}")
        return False

def process_dicom(dcm_file, sender_address, sender_aet, receiver_aet, bookkeeper_address='', bookkeeper_token='') -> Optional[Path]:
    """Process the DICOM file according to the provided arguments."""
    dcm_file = Path(dcm_file)
    
    try:
        dataset = pydicom.dcmread(dcm_file, stop_before_pixels=True)
    except pydicom.errors.InvalidDicomError as e:
        write_error_information(dcm_file, f"Unable to read DICOM file {dcm_file.name}: {e}")
        return None

    series_uid = str(dataset.get("SeriesInstanceUID", ""))
    sop_instance_uid = str(dataset.get("SOPInstanceUID", ""))
    
    new_filename = f"{series_uid}#{dcm_file.name}"
    series_folder = dcm_file.parent / series_uid

    if not create_series_folder(dcm_file.parent, series_uid):
        write_error_information(dcm_file, f"Unable to create series folder for {series_uid}")
        return None

    new_dcm_file: Path = series_folder / new_filename
    try:
        shutil.move(dcm_file, new_dcm_file)
    except OSError as e:
        write_error_information(dcm_file, f"Unable to move DICOM file to {new_dcm_file}: {e}")
        return None

    extra_tags_file = Path("./dcm_extra_tags")
    if not extra_tags_file.exists():
        extra_tags_file = Path(sys.argv[0]).parent / "dcm_extra_tags"
    
    additional_tags = read_extra_tags(dataset, extra_tags_file)

    if not write_tags_file(new_dcm_file, dcm_file.name, dataset, MAIN_TAGS, additional_tags, 
                           sender_address, sender_aet, receiver_aet):
        write_error_information(new_dcm_file, f"Unable to write tags file for {new_filename}")
        # Move DICOM file back to original location
        shutil.move(str(new_dcm_file), dcm_file)
        return None

    send_bookkeeper_post(new_filename, sop_instance_uid, series_uid, bookkeeper_address, bookkeeper_token)
    return new_dcm_file

def main() -> int:
    parser = argparse.ArgumentParser(description=f"getdcmtags Version {VERSION}")
    parser.add_argument("dcm_file", help="DICOM file to analyze")
    parser.add_argument("sender_address", help="Sender address")
    parser.add_argument("sender_aet", help="Sender AET")
    parser.add_argument("receiver_aet", help="Receiver AET")
    parser.add_argument("--bookkeeper_address", default="", help="IP:port of bookkeeper")
    parser.add_argument("--bookkeeper_token", default="", help="API key for bookkeeper")

    args = parser.parse_args()

    if not process_dicom(
        dcm_file=args.dcm_file,
        sender_address=args.sender_address,
        sender_aet=args.sender_aet,
        receiver_aet=args.receiver_aet,
        bookkeeper_address=args.bookkeeper_address,
        bookkeeper_token=args.bookkeeper_token
    ):
        return 1
    else:
        return 0
    
if __name__ == "__main__":
    sys.exit(main())