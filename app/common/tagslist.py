"""
tagslist.py
===========
Helper functions for displaying a list of DICOM tags available for routing in the graphical user interface of mercure.
"""

from typing import Dict, List

alltags: Dict[str, str] = {}
sortedtags: List[str] = []

default_tags: Dict[str, str] = {
    # Add special tags that are obtained from the command-line arguments
    "SenderAddress": "127.0.0.1",
    "SenderAET": "STORESCU",
    "ReceiverAET": "ANY-SCP",
    # Add common DICOM tags
    "SpecificCharacterSet": "ISO_IR 100",
    "Modality": "MR",
    "BodyPartExamined": "BRAIN",
    "ProtocolName": "COR T1 PIT(POST)",
    "RetrieveAETitle": "STORESCP",
    "StationAETitle": "ANY-SCP",
    "Manufacturer": "mercure",
    "ManufacturerModelName": "Router",
    "StudyDescription": "NEURO^HEAD",
    "CodeValue": "IMG11291",
    "CodeMeaning": "MRI BRAIN PITUITARY WITH AND WITHOUT IV CONTRAST",
    "SeriesDescription": "COR T1 POST",
    "PatientName": "Knight^Michael",
    "PatientID": "987654321",
    "PatientBirthDate": "20100101",
    "PatientSex": "M",
    "AccessionNumber": "1234567",
    "ReferringPhysicianName": "Tanner^Willie",
    "StudyID": "243211348",
    "SeriesNumber": "99",
    "SOPInstanceUID": "1.2.256.0.7220020.3.1.3.541411159.31.1254476944.91518",
    "SeriesInstanceUID": "1.2.256.0.7230020.3.1.3.531431169.31.1254476944.91508",
    "StudyInstanceUID": "1.2.226.0.7231010.3.1.2.531431169.31.1554576944.99502",
    "SeriesDate": "20190131",
    "SeriesTime": "134112.100000",
    "AcquisitionDate": "20190131",
    "AcquisitionTime": "134112.100000",
    "SequenceName": "*se2d1",
    "ScanningSequence": "SE",
    "SequenceVariant": "SPOSP",
    "MagneticFieldStrength": "1.5",
    "StationName": "MR20492",
    "DeviceSerialNumber": "12345",
    "DeviceUID": "1.2.276.0.7230010.3.1.4.8323329.22517.1564764826.40200",
    "SoftwareVersions": "mercure MR A10",
    "ContrastBolusAgent": "8.0 ML JUICE",
    "ImageComments": "Comment on image",
    "SliceThickness": "3",
    "InstanceNumber": "12",
    "AcquisitionNumber": "15",
    "InstitutionName": "Some institution",
    "MediaStorageSOPClassUID": "1.2.840.10008.5.1.4.1.1.4",
    "AcquisitionType": "SPIRAL",
    "ImageType": "ORIGINAL"
}
