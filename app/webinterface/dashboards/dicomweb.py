"""
dicomweb.py
===========
DICOMweb interface for handling DICOM uploads via STOW-RS protocol.
"""

import hashlib
import io
import os
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional, Tuple

import common.config as config
import common.monitor as monitor
# Standard python includes
import daiquiri
# DICOM-related includes
import pydicom
# App-specific includes
from decoRouter import Router as decoRouter
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from webinterface.common import rq_fast_queue
from webinterface.dashboards.common import ClassBasedRQTask, invoke_getdcmtags

router = decoRouter()
logger = daiquiri.getLogger("dicomweb")


class DicomFile:
    """Class representing a DICOM file with metadata and content."""
    file_path: Path
    file_hash: str
    study_uid: str
    series_uid: str
    sop_uid: str

    def __init__(self, file_path: Path, file_hash: str, study_uid: str, series_uid: str, sop_uid: str):
        self.file_path = file_path
        self.file_hash = file_hash
        self.study_uid = study_uid
        self.series_uid = series_uid
        self.sop_uid = sop_uid


class DicomValidationError(Exception):
    """Custom exception for DICOM validation errors"""
    pass


async def save_dicom_file(dicom_data: bytes, upload_dir: Path) -> Tuple[Path, str]:
    """
    Save DICOM data to temporary file and generate hash

    Args:
        dicom_data: Raw DICOM file bytes
        upload_dir: Directory to save file

    Returns:
        Tuple of (file_path, file_hash)
    """
    # Generate hash for filename
    file_hash = hashlib.sha256(dicom_data).hexdigest()

    # Create temp file with hash name
    file_path = upload_dir / f"{file_hash}.dcm"

    with open(file_path, "wb") as f:
        f.write(dicom_data)

    return file_path, file_hash


# def validate_dicom(file_path: Path) -> Dataset:
#     """
#     Validate DICOM file and return dataset if valid

#     Args:
#         file_path: Path to DICOM file

#     Returns:
#         PyDicom dataset if valid

#     Raises:
#         DicomValidationError if validation fails
#     """
#     try:
#         # Attempt to read DICOM file
#         ds = pydicom.dcmread(str(file_path), stop_before_pixels=True)

#         # Check required fields
#         required_fields = [
#             # 'PatientID',
#             'StudyInstanceUID',
#             'SeriesInstanceUID',
#             # 'SOPInstanceUID'
#         ]

#         missing = [field for field in required_fields if not hasattr(ds, field)]

#         if missing:
#             raise DicomValidationError(f"Missing required DICOM fields: {', '.join(missing)}")

#         # Validate UIDs
#         if not ds.StudyInstanceUID.strip() or not ds.SeriesInstanceUID.strip():
#             raise DicomValidationError("Invalid Study or Series UID")

#         return ds

#     except InvalidDicomError as e:
#         raise DicomValidationError(f"Invalid DICOM format: {str(e)}")
#     except Exception as e:
#         raise DicomValidationError(f"Error validating DICOM: {str(e)}")


# async def process_dicom_upload(
#     dicom_files: List[bytes]
# ) -> Tuple[List[DicomFile], List[Dict]]:
#     """
#     Process uploaded DICOM files

#     Args:
#         dicom_files: List of raw DICOM file bytes

#     Returns:
#         Tuple of (valid_files, errors)
#     """
#     valid_files = []
#     errors = []

#     # Create temp directory for processing
#     with tempfile.TemporaryDirectory() as temp_dir:
#         upload_dir = Path(temp_dir)

#         for i, dicom_data in enumerate(dicom_files):
#             try:
#                 # Save file
#                 file_path, file_hash = await save_dicom_file(dicom_data, upload_dir)

#                 # Validate DICOM
#                 ds = validate_dicom(file_path)

#                 # Create DicomFile object
#                 dicom_file = DicomFile(
#                     file_path=str(file_path),
#                     file_hash=file_hash,
#                     study_uid=ds.StudyInstanceUID,
#                     series_uid=ds.SeriesInstanceUID,
#                     sop_uid=ds.get('SOPInstanceUID')
#                 )

#                 valid_files.append(dicom_file)

#             except DicomValidationError as e:
#                 logger.exception(f"DicomValidationError at index {i}: {str(e)}")
#                 errors.append({
#                     "index": i,
#                     "error": str(e)
#                 })
#             except Exception as e:
#                 logger.exception(f"Unexpected error at index {i}: {str(e)}")
#                 errors.append({
#                     "index": i,
#                     "error": f"Unexpected error: {str(e)}"
#                 })

#     return valid_files, errors


###################################################################################
# DICOMweb endpoints
###################################################################################


@router.get("/")
async def index(request) -> Response:
    return JSONResponse({"ok": True})


@router.post("/force-rule/{force_rule}/studies")
@requires(["authenticated"])
async def studies_force(request: Request) -> Response:
    return await stow_rs(request, request.path_params['force_rule'])


@router.post("/studies")
@requires(["authenticated"])
async def studies(request: Request) -> Response:
    return await stow_rs(request, None)


@requires(["authenticated"])
async def stow_rs(request: Request, force_rule: Optional[str]) -> Response:
    """
    Handle STOW-RS requests for uploading DICOM instances
    """
    try:
        # Validate content type
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/related"):
            return JSONResponse(
                {"error": "Invalid content type - must be multipart/related"},
                status_code=415
            )

        # Extract boundary
        try:
            boundary = content_type.split("boundary=")[1].strip().strip('"')
        except IndexError:
            return JSONResponse(
                {"error": "Missing boundary in content-type"},
                status_code=400
            )
        # Process multipart DICOM data
        body = await request.body()

        # Split on boundary
        split_on = f"--{boundary}".encode()
        parts = body.split(split_on)
        # logger.info(f"Split on {split_on}")
        # logger.info(f"{len(parts)} parts received")
        dicom_parts = []
        zip_parts = []
        # Process each part
        for part in parts[1:-1]:
            # Split headers from content
            try:
                headers, content = part.split(b'\r\n\r\n', 1)
                if content[-2:] == b'\r\n':
                    content = content[:-2]
                # logger.info(f"Headers: {headers}")
                headers = dict(line.split(b': ') for line in headers.splitlines() if line)
                # logger.info(f"Headers dict: {headers}")
                if any(map(content.startswith, [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'])):
                    zip_parts.append(content)
                    continue
                if headers.get(b'Content-Type') == b'application/dicom':
                    dicom_parts.append(content)
                elif headers.get(b'Content-Type') == b'application/zip':
                    zip_parts.append(content)
            except ValueError:
                logger.exception("Invalid part format")
                continue

        if not dicom_parts and not zip_parts:
            logger.error("No DICOM instances found in request")
            return JSONResponse(
                {"error": "No DICOM instances found in request"},
                status_code=400
            )
        logger.info(f"Found {len(dicom_parts)} DICOM parts and {len(zip_parts)} ZIP parts")

        with tempfile.TemporaryDirectory(prefix="route-tmp") as route_dir:
            if zip_files := [zipfile.ZipFile(io.BytesIO(part)) for part in zip_parts]:
                # Process each ZIP file separately
                for i, zip_file in enumerate(zip_files):
                    with tempfile.TemporaryDirectory(prefix=f"zip-{i}-") as zip_extract_dir, tempfile.TemporaryDirectory(prefix=f"zip-extracted-{i}-") as tempdir:
                        # If the size is less than 132 bytes, it's not a DICOM file
                        files_to_extract = [k for k in zip_file.filelist if k.file_size > 128+4]
                        logger.info(f"Extracting {files_to_extract} files from ZIP")
                        zip_file.extractall(zip_extract_dir, files_to_extract)  # Extract the ZIP file to a temporary directory
                        dupes = defaultdict(lambda: 1)
                        for file in Path(zip_extract_dir).rglob('*'):
                            if not file.is_file():  # Skip directories
                                continue

                            # Skip files that are not DICOM files
                            with file.open('rb') as f:
                                f.seek(128)
                                if f.read(4) != b'DICM':
                                    continue

                            dest_file_name = Path(tempdir) / file.name
                            while dest_file_name.exists():
                                dest_file_name = Path(tempdir) / f"{file.stem}_{dupes[dupes[file.name]]}{file.suffix}"
                                dupes[dest_file_name] += 1

                            file.rename(dest_file_name)
                            logger.info(f"Renamed {file} to {dest_file_name}")
                            invoke_getdcmtags(dest_file_name, None, force_rule)

                        for p in Path(tempdir).iterdir():
                            if p.is_dir():
                                shutil.move(p, Path(route_dir) / p.name)
            # ------------/

            # ------------\
            i = 0
            for dicom_part in dicom_parts:
                while (path := Path(route_dir) / f"dicom_{i}").exists():
                    i += 1
                logger.info(path)
                with path.open('wb') as f:
                    f.write(dicom_part)
                invoke_getdcmtags(path, None, force_rule)
                i += 1

            for p in list(Path(route_dir).iterdir()):
                logger.info(f"????? {p}")
                if p.is_dir():
                    logger.info(f"Moving {p} to {config.mercure.incoming_folder}")
                    shutil.move(p, Path(config.mercure.incoming_folder) / p.name)
                logger.info(list(Path(config.mercure.incoming_folder).rglob('*')))

        return JSONResponse({
            "success": True,
            "instanceCount": len(dicom_parts)
        })

    except Exception as e:
        logger.exception(f"Error processing STOW-RS request: {str(e)}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )

dicomweb_app = Starlette(routes=router)
