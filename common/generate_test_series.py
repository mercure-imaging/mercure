#!/usr/bin/python3

import datetime
import hashlib
import random
import string
import sys
from pathlib import Path
from typing import Any, List, Optional, Union

# import numpy as np  # type: ignore
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID

# File meta info data elements


# def mandelbrot(m: int = 512, n: int = 256) -> Any:
#     x = np.linspace(-2, 1, num=m).reshape((1, m))
#     y = np.linspace(-1, 1, num=n).reshape((n, 1))
#     C = np.tile(x, (n, 1)) + 1j * np.tile(y, (1, m))

#     Z = np.zeros((n, m), dtype=complex)
#     M = np.full((n, m), True, dtype=bool)
#     for i in range(20):
#         Z[M] = Z[M] * Z[M] + C[M]
#         M[np.abs(Z) > 2] = False
#     return M.astype(np.uint8)


# def julia(arg: complex, m: int = 256, n: int = 512) -> Any:
#     x = np.linspace(-1, 1, num=m).reshape((1, m))
#     y = np.linspace(-2, 2, num=n).reshape((n, 1))
#     C = np.tile(x, (n, 1)) + 1j * np.tile(y, (1, m))

#     # Z = np.zeros((n, m), dtype=complex)
#     M = np.full((n, m), True, dtype=bool)
#     K = np.full((n, m), 1, dtype=np.uint16)

#     for i in range(20):
#         C[M] = C[M] * C[M] + arg
#         M[np.abs(C) > 2] = False
#         # np.log(np.abs(C)+.1).astype('uint16'))
#         np.putmask(K, np.abs(C) > 2, 0)
#         # K[np.abs(C) > 2] = np.abs(C)
#     return K


def nums(n: int, source: Optional[str] = None) -> str:
    if not source:
        return "".join(random.choice(string.digits) for i in range(n))
    else:
        return "".join([str(int(x)) for x in hashlib.md5(source.encode()).digest()])[0:n]


dt = datetime.datetime.now()


def generate_file(
    study: str,
    series: str,
    slice_number: int,
    acc: str,
    study_uid: str,
    desc: str,
    image: Any,
    orientation: List[List[float]] = [[1, 0, 0], [0, 1, 0]],
    patient_name: Optional[str] = "Julia^Set",
    patient_id: Optional[str] = "JULIATEST",
) -> Dataset:
    # normal_vec = np.cross(orientation[0], orientation[1])

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationGroupLength = 200
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = UID("1.2.840.10008.5.1.4.1.1.4")

    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid(prefix="1.2.276.0.7230010.3.1.4.")
    file_meta.TransferSyntaxUID = UID("1.2.840.10008.1.2.1")
    file_meta.ImplementationClassUID = UID("1.2.276.0.7230010.3.0.3.6.2")
    file_meta.ImplementationVersionName = "OFFIS_DCMTK_362"

    # Main data elements
    ds = Dataset()
    ds.preamble = 128 * b"\0"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    # pydicom.uid.generate_uid(
    #    prefix='1.2.276.0.7230010.3.1.4.')
    ds.StudyDate = dt.strftime("%Y%m%d")
    ds.StudyTime = dt.strftime("%H%M")
    ds.AccessionNumber = acc
    ds.Modality = "MR"
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "O"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series
    ds.FrameOfReferenceUID = series
    ds.SeriesDescription = desc
    # ds.SeriesNumber = 1
    ds.InstanceNumber = str(slice_number + 1)
    ds.StudyID = study
    ds.ImageComments = "NOT FOR DIAGNOSTIC USE"
    ds.PatientPosition = "HFS"
    ds.ImageOrientationPatient = [*orientation[0], *orientation[1]]
    ds.SpacingBetweenSlices = 7.5
    # ds.ImagePositionPatient = list([0, 0, 0] + normal_vec * ds.SpacingBetweenSlices * slice_number)
    ds.SliceLocation = 7.5 * slice_number + 170
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SliceThickness = 5
    ds.PixelData = b"\x00" * (100 * 100)
    ds.NumberOfFrames = "1"
    ds.Rows = 100
    ds.Columns = 100
    ds.PixelSpacing = [2, 2]
    # ds.PixelAspectRatio = [1, 1]
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.file_meta = file_meta
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    return ds


def generate_test_series(
    pt: complex = -0.3 - 0.0j,
    n: int = 10,
    orientation: List[List[float]] = [[1, 0, 0], [0, 1, 0]],
    accession: Optional[str] = None,
    study_id: Optional[str] = None,
    patient_name: Optional[str] = None,
    patient_id: Optional[str] = None,
    series_description: Optional[str] = None,
) -> List[Dataset]:
    acc = accession or nums(7)
    study = study_id or nums(8)
    series = pydicom.uid.generate_uid(prefix="1.2.276.0.7230010.3.1.3.")
    study_uid = pydicom.uid.generate_uid(prefix="1.2.276.0.7230010.3.1.2.", entropy_srcs=[study])
    description = series_description or f"Julia set around {pt}"
    if patient_name and not patient_id:
        patient_id = nums(8, patient_name)
    print(f"acc {acc}, study {study}, series {series}, description {description}")
    datasets = []

    for i in range(n):
        pt_at = pt + 0.1j * (i - n / 2)
        # array = julia(pt_at)
        # print(array)
        datasets.append(
            generate_file(
                study,
                series,
                i,
                acc,
                study_uid,
                description,
                None,
                # array,
                orientation,
                patient_name,
                patient_id,
            )
        )
    return datasets


def generate_series(
    k: Union[str, Path],
    n: int,
    orientation: List[List[float]] = [[1, 0, 0], [0, 1, 0]],
    series_description: Optional[str] = "Julia set",
) -> List[Path]:
    f: Path = Path(k)
    f.mkdir(parents=True, exist_ok=True)
    datasets = generate_test_series(0.3 - 0.0j, n, orientation, series_description=series_description)
    files = []
    for i, d in enumerate(datasets):
        filename = f / f"slice.{i}.dcm"
        d.save_as(filename)
        files.append(filename)
    return files


def generate_several_protocols(base_path: str) -> List[Path]:
    f: Path = Path(base_path)
    f.mkdir(parents=True, exist_ok=True)
    protocols = ["PROT1", "PROT2", "PROT1_DL", "PROT2_DL"]
    acc = nums(7)
    study = nums(8)
    patient_name = "Patient 1"
    files = []
    for p in protocols:
        datasets = generate_test_series(
            0.3 - 0.0j,
            5,
            [[1, 0, 0], [0, 1, 0]],
            acc,
            study,
            patient_name,
            None,
            p,
        )
        for i, d in enumerate(datasets):
            (f / p).mkdir(exist_ok=True)
            filename = f / p / f"slice.{i}.dcm"
            d.save_as(filename)
            files.append(filename)
    return files


if __name__ == "__main__":
    generate_series(sys.argv[1], int(sys.argv[2]))
    # print(generate_test("/vagrant/blinding_test"))

# result.save_as(f'/vagrant/test_series/slice.{i}.dcm')
# ds.save_as(r'../mandel_from_codify.dcm', write_like_original=False)
