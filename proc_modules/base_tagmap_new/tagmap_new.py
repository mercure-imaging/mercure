"""
dicom_tag_manipulator.py
=========================
Processing module for Mercure that adds private DICOM tags and modifies standard tags

This module performs the following modifications:
1. Sets Institution Name (0008,0080) to "NVRA"
2. Sets Institutional Department Name (0008,1040) to "NVRA"
3. Creates private DICOM tags in the 7771 group:
   - (7771,0010): "NL_PRIVATE" - Private Creator ID
   - (7771,1001): "PIPELINE" - Pipeline identifier
   - (7771,1002): "MAIN" - Main identifier

If the private tags already exist, the module makes no changes and simply
copies the files to the output folder.
"""

# Standard Python includes
import os
import sys
import json
from pathlib import Path

# Imports for loading DICOMs
import pydicom
from pydicom.uid import generate_uid


def process_image(file, in_folder, out_folder, series_uid, settings):
    """
    Processes the DICOM image specified by 'file'. This function will read the
    file from the in_folder, add private tags if they don't exist, and save it 
    to the out_folder using a new series UID given by series_uid.
    """
    dcm_file_in = Path(in_folder) / file
    # Compose the filename of the modified DICOM using the new series UID
    out_filename = series_uid + "#" + file.split("#", 1)[1]
    dcm_file_out = Path(out_folder) / out_filename

    # Load the input slice
    ds = pydicom.dcmread(dcm_file_in)
    
    # Check if private tags already exist
    # Private tags are (7771,0010), (7771,1001), and (7771,1002)
    tags_exist = (
        (0x7771, 0x0010) in ds and
        (0x7771, 0x1001) in ds and
        (0x7771, 0x1002) in ds
    )
    
    if not tags_exist:
        # Tags don't exist, so we'll add them and modify the series
        
        # Set the new series UID
        ds.SeriesInstanceUID = series_uid
        
        # Set a UID for this slice (every slice needs to have a unique instance UID)
        ds.SOPInstanceUID = generate_uid()
        
        # Add an offset to the series number (to avoid collision in PACS if sending back into the same study)
        ds.SeriesNumber = ds.SeriesNumber + settings["series_offset"]
        
        # Update the series description to indicate this is a modified series
        ds.SeriesDescription = "MODIFIED(" + ds.SeriesDescription + ")"
        
        # ===== STANDARD TAG MODIFICATION =====
        # Set Institution Name (0008,0080) to "NVRA"
        ds.InstitutionName = settings["institution_name"]
        
        # Set Institutional Department Name (0008,1040) to "NVRA"
        ds.InstitutionalDepartmentName = settings["department_name"]
        
        # ===== PRIVATE TAG CREATION =====
        # Create private tag (7771,0010) with VR Type LO and value "NL_PRIVATE"
        # This tag identifies the private creator
        ds.add_new(0x77710010, 'LO', settings["private_creator"])
        
        # Create private tag (7771,1001) with VR Type LO and value "PIPELINE"
        ds.add_new(0x77711001, 'LO', settings["pipeline_value"])
        
        # Create private tag (7771,1002) with VR Type LO and value "MAIN"
        ds.add_new(0x77711002, 'LO', settings["main_value"])
    else:
        # Tags already exist - keep original series UID and instance UID
        # Just copy the file without modification
        pass
    
    # Write the DICOM file to the output folder
    ds.save_as(dcm_file_out)


def main(args=sys.argv[1:]):
    """
    Main entry function of the DICOM tag manipulation module. 
    The module is called with two arguments from the function docker-entrypoint.sh:
    'dicom_tag_manipulator [input-folder] [output-folder]'. The exact paths of the 
    input-folder and output-folder are provided by mercure via environment variables
    """
    # Print some output, so that it can be seen in the logfile that the module was executed
    print("DICOM Private Tag Creator Module - Starting")

    # Check if the input and output folders are provided as arguments
    if len(sys.argv) < 3:
        print("Error: Missing arguments!")
        print("Usage: dicom_tag_manipulator [input-folder] [output-folder]")
        sys.exit(1)

    # Check if the input and output folders actually exist
    in_folder = sys.argv[1]
    out_folder = sys.argv[2]
    if not Path(in_folder).exists() or not Path(out_folder).exists():
        print("IN/OUT paths do not exist")
        sys.exit(1)

    # Load the task.json file, which contains the settings for the processing module
    try:
        with open(Path(in_folder) / "task.json", "r") as json_file:
            task = json.load(json_file)
    except Exception:
        print("Error: Task file task.json not found")
        sys.exit(1)

    # Create default values for all module settings
    settings = {
        "institution_name": "NVRA",       # Value for Institution Name tag (0008,0080)
        "department_name": "NVRA",        # Value for Institutional Department Name tag (0008,1040)
        "private_creator": "NL_PRIVATE",  # Value for private creator tag (7771,0010)
        "pipeline_value": "PIPELINE",     # Value for pipeline tag (7771,1001)
        "main_value": "MAIN",             # Value for main tag (7771,1002)
        "series_offset": 1000             # Offset to add to series number
    }

    # Overwrite default values with settings from the task file (if present)
    if task.get("process", ""):
        settings.update(task["process"].get("settings", {}))

    # Print the configured tag values for debugging
    print(f"Institution Name: {settings['institution_name']}")
    print(f"Institutional Department Name: {settings['department_name']}")
    print(f"Private Creator: {settings['private_creator']}")
    print(f"Pipeline Value: {settings['pipeline_value']}")
    print(f"Main Value: {settings['main_value']}")

    # Collect all DICOM series in the input folder. By convention, DICOM files provided by
    # mercure have the format [series_UID]#[file_UID].dcm. Thus, by splitting the file
    # name at the "#" character, the series UID can be obtained
    series = {}
    for entry in os.scandir(in_folder):
        if entry.name.endswith(".dcm") and not entry.is_dir():
            # Get the Series UID from the file name
            seriesString = entry.name.split("#", 1)[0]
            # If this is the first image of the series, create new file list for the series
            if seriesString not in series.keys():
                series[seriesString] = []
            # Add the current file to the file list
            series[seriesString].append(entry.name)

    # Now loop over all series found
    for item in series:
        # Create a new series UID, which will be used for the modified DICOM series (to avoid
        # collision with the original series)
        series_uid = generate_uid()
        # Now loop over all slices of the current series and call the processing function
        for image_filename in series[item]:
            process_image(image_filename, in_folder, out_folder, series_uid, settings)
    
    print(f"Processed {sum(len(files) for files in series.values())} DICOM files")
    print("DICOM Private Tag Creator Module - Complete")


if __name__ == "__main__":
    main()