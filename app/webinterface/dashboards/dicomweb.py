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
from typing import List
from urllib.parse import parse_qs

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
from webinterface.common import rq_fast_queue, templates
from webinterface.dashboards.common import ClassBasedRQTask, invoke_getdcmtags

from .common import router

logger = daiquiri.getLogger("dicomweb")


@router.get("/")
async def index(request) -> Response:
    return JSONResponse({"ok": True})


class MultipartData:
    dicoms: List[bytes]
    zips:  List[bytes]
    form_data: List[bytes]

    def __init__(self, dicoms, zips, form_data):
        self.dicoms = dicoms
        self.zips = zips
        self.form_data = form_data


async def parse_multipart_data(request: Request):
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
    form_data_parts = []
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
            elif headers.get(b'Content-Type') == b'application/x-www-form-urlencoded':
                form_data_parts.append(content)
        except ValueError:
            logger.exception("Invalid part format")
            continue

    logger.info(f"Found {len(dicom_parts)} DICOM parts and {len(zip_parts)} ZIP parts")

    return MultipartData(dicom_parts, zip_parts, form_data_parts)


def extract_zip(zip_file, extract_to, force_rule):
    n_extracted = 0
    with tempfile.TemporaryDirectory(prefix=f"zip-") as zip_extract_dir, tempfile.TemporaryDirectory(prefix=f"zip-extracted-") as tempdir:
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
            n_extracted += 1

        for p in Path(tempdir).iterdir():
            if p.is_dir():
                shutil.move(p, Path(extract_to) / p.name)
    return n_extracted


@router.get("/upload")
@requires("authenticated", redirect="login")
async def upload(request):
    template = "dashboards/dicom_upload.html"
    context = {
        "request": request,
        "page": "tools",
        "rules": [name for name, _ in config.mercure.rules.items()],
        "datasets": [p.name for p in Path(config.mercure.jobs_folder + f"/uploaded_datasets/{request.user.display_name}").iterdir()],
        "tab": "upload",
    }
    logger.info(context)
    return templates.TemplateResponse(template, context)


@router.get("/dataset/{dataset_id}")
@router.post("/dataset/{dataset_id}")
@router.delete("/dataset/{dataset_id}")
@requires("authenticated", redirect="login")
async def dataset_operation(request: Request):
    dataset_id = request.path_params["dataset_id"]
    folder = (Path(config.mercure.jobs_folder) / "uploaded_datasets" / request.user.display_name / dataset_id).resolve()
    # check that folder is really a subdirectory of config.mercure.jobs_folder
    if not Path(config.mercure.jobs_folder).resolve() in folder.parents:
        return JSONResponse({"error": "Dataset not found"}, status_code=404)

    if not folder.exists():
        return JSONResponse({"error": "Dataset not found"}, status_code=404)

    if request.method == "DELETE":
        shutil.rmtree(folder)
        return JSONResponse({"status": "success"})
    elif request.method == "GET":
        dataset = {
            "id": dataset_id,
            "series_count": [f.name for f in folder.iterdir() if f.is_dir()]
        }
        return JSONResponse(dataset)
    elif request.method == "POST":
        # Handle POST request to resubmit the dataset
        for p in list(Path(folder).iterdir()):
            if p.is_dir():
                logger.info(f"Moving {p} to {config.mercure.incoming_folder}")
                shutil.move(p, Path(config.mercure.incoming_folder) / p.name)
        return JSONResponse({"status": "success"})
    else:
        return JSONResponse({"error": "Method not allowed"}, status_code=405)
    return JSONResponse({"status": "error"}, status_code=501)


@router.post("/upload/store")
@requires(["authenticated"])
async def stow_rs(request: Request) -> Response:
    """
    Handle STOW-RS requests for uploading DICOM instances
    """
    try:
        # Parse multipart data
        multipart_data = await parse_multipart_data(request)
        if not multipart_data.dicoms and not multipart_data.zips:
            logger.error("No DICOM instances found in request")
            return JSONResponse(
                {"error": "No DICOM instances found in request"},
                status_code=400
            )
        form_data = {}
        for f in multipart_data.form_data:
            form_data.update({
                key.decode(): values[0].decode() if len(values) == 1 else map(lambda x: x.decode(), values)
                for key, values in parse_qs(f).items()
            })
            # decode the form data and add it to the request

        force_rule = form_data.get("force_rule", None)
        save_dataset = form_data.get("save_dataset", "false").lower() == "true"
        save_dataset_as = form_data.get("dataset_name", None)

        logger.info(f"Form data: {form_data}")

        with tempfile.TemporaryDirectory(prefix="route-tmp") as route_dir:
            n_dicoms = 0
            if zip_files := [zipfile.ZipFile(io.BytesIO(part)) for part in multipart_data.zips]:
                for zip_file in zip_files:
                    n_dicoms += extract_zip(zip_file, route_dir, force_rule)

            # ------------/

            # ------------\
            i = 0
            for dicom_part in multipart_data.dicoms:
                while (path := Path(route_dir) / f"dicom_{i}").exists():
                    i += 1
                logger.info(path)
                with path.open('wb') as f:
                    f.write(dicom_part)
                invoke_getdcmtags(path, None, force_rule)
                n_dicoms += 1
                i += 1

            if save_dataset:
                basedir = config.mercure.jobs_folder + f"/uploaded_datasets/{request.user.display_name}"
                os.makedirs(basedir, exist_ok=True)
                shutil.copytree(route_dir, basedir + "/" + save_dataset_as)
            for p in list(Path(route_dir).iterdir()):
                if p.is_dir():
                    logger.info(f"Moving {p} to {config.mercure.incoming_folder}")
                    shutil.move(p, Path(config.mercure.incoming_folder) / p.name)

        return JSONResponse({
            "success": True,
            "file_count": n_dicoms
        })

    except Exception as e:
        logger.exception(f"Error processing STOW-RS request: {str(e)}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )

dicomweb_app = Starlette(routes=router)
