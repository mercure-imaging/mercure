from pathlib import Path
from typing import Dict, Generator, List
from dicomweb_client import DICOMfileClient
from requests.exceptions import HTTPError
import time
import pydicom
from common.types import DicomWebTarget, TaskDispatch, Task
from .base import ProgressInfo, TargetHandler
from .registry import handler_for

from dicomweb_client.api import DICOMwebClient
from dicomweb_client.session_utils import create_session_from_user_pass


import common.config as config

logger = config.get_logger()


@handler_for(DicomWebTarget)
class DicomWebTargetHandler(TargetHandler[DicomWebTarget]):
    view_template = "targets/dicomweb.html"
    edit_template = "targets/dicomweb-edit.html"
    # test_template = "targets/dicomweb-test.html"
    icon = "fa-share-alt"
    display_name = "DICOMweb"

    def create_client(self, target: DicomWebTarget):
        session = None
        headers = None
        if target.url.startswith("file://"):
            return DICOMfileClient(url=target.url, in_memory=True, update_db=True)
          
        if target.http_user and target.http_password:
            session = create_session_from_user_pass(username=target.http_user, password=target.http_password)
        elif target.access_token:
            headers = {"Authorization": "Bearer {}".format(target.access_token)}

        client = DICOMwebClient(
            url=target.url,
            qido_url_prefix=target.qido_url_prefix,
            wado_url_prefix=target.wado_url_prefix,
            stow_url_prefix=target.stow_url_prefix,
            session=session,
            headers=headers,
        )
        return client

    def find_from_target(self, target: DicomWebTarget, accession: str) -> List[pydicom.Dataset]:
        client = self.create_client(target)
        metadata = client.search_for_series(search_filters={'AccessionNumber': accession}, get_remaining=True)
        return [pydicom.Dataset.from_json(ds) for ds in metadata]

    def get_from_target(self, target: DicomWebTarget, accession, path) -> Generator[ProgressInfo, None, None]:
        client = self.create_client(target)
        series = client.search_for_series(search_filters={'AccessionNumber': accession}, get_remaining=True)
        if not series:
            raise ValueError("No series found with accession number {}".format(accession))
        n = 0
        remaining = 0
        for s in series:
            instances = client.retrieve_series(s['0020000D']['Value'][0], s['0020000E']['Value'][0])
            remaining += len(instances)
            for instance in instances:
                sop_instance_uid = instance.get('SOPInstanceUID')
                filename = f"{path}/{sop_instance_uid}.dcm"
                instance.save_as(filename)
                n += 1
                remaining -= 1
                time.sleep(1)
                yield ProgressInfo(n, remaining, f'{n} / {n + remaining}')
        time.sleep(1)

    def send_to_target(
        self, task_id: str, target: DicomWebTarget, dispatch_info: TaskDispatch, source_folder: Path, task: Task
    ) -> str:
        client = self.create_client(target)
        datasets = [pydicom.dcmread(str(k)) for k in source_folder.glob("**/*.dcm")]
        response = client.store_instances(datasets)
        if len(response.ReferencedSOPSequence) != len(datasets):
            raise Exception("Did not store all datasets", response)

        return ""

    def from_form(self, form: dict, factory, current_target) -> DicomWebTarget:
        url = form["url"]

        for x in [
            "qido_url_prefix",
            "wado_url_prefix",
            "stow_url_prefix",
            "http_user",
            "http_password",
            "access_token",
        ]:
            if x in form and not form[x]:
                form[x] = None

        return DicomWebTarget(**form)

    async def test_connection(self, target: DicomWebTarget, target_name: str):
        client = self.create_client(target)

        results = {}
        try:
            result = client._http_get(target.url)
            results["authentication"] = True
        except HTTPError as e:
            if e.errno == 401:
                results["authentication"] = False
            else:
                results["authentication"] = True

        try:
            client.search_for_studies(limit=1)
            results["QIDO_query"] = True
        except HTTPError as e:
            results["QIDO_query"] = False

        return results
