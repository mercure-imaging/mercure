from common.types import Target, TaskDispatch, XnatTarget
import common.config as config
from webinterface.common import async_run

from .registry import handler_for
from .base import TargetHandler

from pathlib import Path
import aiohttp
import pyxnat
from contextlib import contextmanager
import json
import argparse
import tempfile
import os
import zipfile
import datetime
import glob
from pydicom import dcmread

logger = config.get_logger()

@handler_for(XnatTarget)
class XnatTargetHandler(TargetHandler[XnatTarget]):
    view_template = "targets/xnat.html"
    edit_template = "targets/xnat-edit.html"
    test_template = "targets/xnat-test.html"
    icon = "fa-hdd"
    display_name = "XNAT"

    def send_to_target(
        self, task_id: str, target: XnatTarget, dispatch_info: TaskDispatch, source_folder: Path
    ) -> str:
        try:
            _send_dicom_to_xnat(target=target, folder=source_folder, dispatch_info=dispatch_info)
        except ConnectionError as e:
            self.handle_error(e, '')
            raise

        return ""


    def handle_error(self, e, command) -> None:
        logger.error(e)


    async def test_connection(self, target: XnatTarget, target_name: str):
        url = f"{target.host}/data/auth"

        async with aiohttp.ClientSession() as session:
            ping_ok = False

            if target.host:
                ping_result, *_ = await async_run(f"ping -w 1 -c 1 {target.host}")
                if ping_result == 0:
                    ping_ok = True

            try:            
                async with session.get(url, auth=aiohttp.BasicAuth(target.user, target.password)) as resp:
                    response_ok = resp.status == 200
                    text = await resp.text() if not response_ok else ""
                    return dict(ping=ping_ok, loggedin=response_ok, err=text)

            except Exception as e:
                return dict(ping=ping_ok, loggedin=False, err=str(e))


def _send_dicom_to_xnat(target: XnatTarget, dispatch_info: TaskDispatch, folder: Path):
    logger.info(f"Connecting to {dispatch_info.target_name}({target.host}) XNAT server...")
    with InterfaceManager(server=target.host, user=target.user, password=target.password).open() as session: # type: ignore
        project_id = target.project_id
        dicom_file_path = glob.glob(os.path.join(folder, '*.dcm'))[0]
        dcmFile = dcmread(dicom_file_path, stop_before_pixels=True)
        subject_id = f'{dcmFile.PatientID}'
        experiment_id = f"{subject_id}_{datetime.datetime.strptime(dcmFile.StudyDate, '%Y%m%d').strftime('%Y-%m-%d')}" # TODO make it more generic.

        logger.info(f'Uploading {folder} to {dispatch_info.target_name} ...')
        _upload_dicom_session_to_xnat(
            session=session,
            project_id=project_id,
            subject_id=subject_id,
            experiment_label=experiment_id,
            dicom_path=folder,
            overwrite_dicom=True)


def _upload_dicom_session_to_xnat(
        session : pyxnat.Interface,
        project_id,
        subject_id,
        experiment_label,
        dicom_path,
        overwrite_dicom=True):
    """
    Uploads the dicoms from the given path to an XNAT server using the Image Session Import Service API.
    If the dicom_path contains more than one scan, all will be uploaded to the session.
    :param session: a pyxnat.Interface instance
    :param project_id: (str) XNAT's project ID or label
    :param subject_id: (str) XNAT's subject ID or label
    :param experiment_label: (str) XNAT's experiment label or ID
    :param dicom_path: path to directory containing dicom scan(s)
    :param scan_type: the value for the xnat:mrScanData/type field
    :param overwrite_dicom: if True, it will delete any existing Scan with same ID before uploading
    :return: a list of the uploaded scan_uris
    """
    # Create a zip file with the dicom_path in a temporary directory
    with tempfile.TemporaryDirectory() as tmp_path:
        zip_filepath = os.path.join(tmp_path, 'dicom.zip')
        # rename *.dcm files of dicom_path incrementaly and zip them
        with zipfile.ZipFile(zip_filepath, 'w') as zip_file:
            i = 0
            for root, dirs, files in os.walk(dicom_path):
                for file in files:
                    if file.endswith('.dcm'):
                        zip_file.write(os.path.join(root, file), f'{i}.dcm')
                        i += 1

        # Upload zip file to XNAT server using the Image Session Import API
        with open(zip_filepath, 'rb') as data:
            resp = session.post(
                uri='/data/services/import',
                params={
                    'PROJECT_ID': project_id,
                    'SUBJECT_ID': subject_id,
                    'EXPT_LABEL': experiment_label,
                    'rename': 'true',
                    'overwrite': 'delete' if overwrite_dicom else 'append',
                    'inbody': 'true'},
                headers={
                    'Content-Type': 'application/zip'},
                data=data)

            if resp.status_code != 200:
                raise ConnectionError(f'Response not 200 OK while uploading DICOM with Image Session Import Service API. '
                                      f'Response code: {resp.status_code} '
                                      f'Response: {resp}')


class InterfaceManager(object):
    """Manager for `pyxnat.Interface` that enables the use of the `with` python context.
    Using the InterfaceManager along the `with` python context avoids having to call the `disconnect()` method
    after each connection.
    **Methods**
    - `open()`: to use along the `with` context, yields an instance of `pyxnat.Interface` and disconnects automatically
        when the context ends.
    - `open_persistent()`: returns a persistent instance of `pyxnat.Interface`. User must use the `disconnect()` method
        when the use of the session is finished.
    ```python
    interface = InterfaceManager(server='www.myxnat.org', user='user', password='password')
    with interface.open() as session:
         session.get(...)
    session = interface.open_persistent()
    session.get(...)
    session.disconnect()
    ```
    """
    def __init__(self, server, user, password):
        self.host = server
        self.user = user
        self.psswd = password


    @contextmanager
    def open(self):
        try:
            sess = pyxnat.Interface(server=self.host, user=self.user, password=self.psswd)
            yield sess
        finally:
            sess.disconnect()


    def open_persistent(self):
        return pyxnat.Interface(server=self.host, user=self.user, password=self.psswd) 
    