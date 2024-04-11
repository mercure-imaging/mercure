import pydicom
from pydicom.dataset import Dataset

# Create a new DICOM dataset
ds = Dataset()

# Set some mandatory DICOM fields
ds.PatientName = "Doe^John"
ds.PatientID = "123456"
ds.PatientName = b"Fake^\x00Name\xb1"  # This introduces a non-ASCII character in ASCII field
ds.SpecificCharacterSet="ISO_IR 192"
ds.is_little_endian = True
ds.is_implicit_VR = False
# Save the dataset to a DICOM file
ds.save_as("broken_encoding_dicom.dcm")

print("DICOM file with broken encoding has been created.")