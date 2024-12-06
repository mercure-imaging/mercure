import itertools
from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


def generate_dicom_files(accession_number, destination_folder:Path, num_files=10, num_studies=2, num_series=2):
    """
    Generate a folder of DICOM files with the given accession number.

    :param accession_number: The accession number to use for the DICOM files
    :param destination_folder: The parent folder where the accession subfolder will be created
    :param num_files: The number of DICOM files to generate (default: 10)
    """
    # Create the accession subfolder
    
    for (study_n,series_n,file_n) in itertools.product(range(num_studies), range(num_series), range(num_files)):
        if file_n == 0:
            series_uid = generate_uid()
            if series_n == 0:
                study_uid = generate_uid()
        
        ds = Dataset()
        ds.PatientName = "Test^Patient"
        ds.PatientID = "12345"
        ds.StudyDate = "20210101"
        ds.AccessionNumber = accession_number
        ds.is_little_endian = True
        ds.is_implicit_VR = False

        ds.SOPClassUID = CTImageStorage  # CT Image Storage
        ds.SOPInstanceUID = generate_uid()
        ds.InstanceNumber = file_n + 1

        ds.StudyInstanceUID = study_uid
        ds.StudyDescription = f"study_{study_n + 1}"
        ds.SeriesInstanceUID = series_uid
        ds.SeriesNumber = series_n + 1
        ds.SeriesDescription = f"series_{series_n + 1}"

        ds.PixelData = b"\x00" * (100 * 100 * 2) 
        ds.NumberOfFrames = "1"
        ds.Rows = 100
        ds.Columns = 100
        ds.PixelSpacing = [2, 2]
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        # Save the DICOM file in the accession subfolder
        dir = destination_folder / str(accession_number) / ds.StudyDescription / ds.SeriesDescription
        dir.mkdir(parents=True, exist_ok=True)
        filename = f"dicom_file_{file_n+1}.dcm"

        ds.save_as(dir / filename, write_like_original=False)

    print(f"Generated {num_files * num_series * num_studies} DICOM files with accession number {accession_number} in { destination_folder / accession_number}")

if __name__ == "__main__":
    import argparse

    def dir_path(string) -> Path:
        if (p:=Path(string)).is_dir():
            return p
        raise NotADirectoryError(string)

    parser = argparse.ArgumentParser(description="Generate DICOM files with a specific accession number")
    parser.add_argument("accession_number", help="Accession number for the DICOM files")
    parser.add_argument("destination_folder", type=dir_path, help="Parent folder where the accession subfolder will be created")
    parser.add_argument("--num_files", type=int, default=10, help="Number of DICOM files to generate (default: 10)")

    args = parser.parse_args()

    generate_dicom_files(args.accession_number, args.destination_folder, args.num_files)
