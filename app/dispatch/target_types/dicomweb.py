import os
from pathlib import Path
import sqlite3
from typing import Dict, Generator, List, Union
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
    can_pull = True

    def create_client(self, target: DicomWebTarget) -> Union[DICOMfileClient, DICOMwebClient]:
        session = None
        headers = None
        if target.url.startswith("file://"):
            try:
                return DICOMfileClient(url=target.url, in_memory=False, update_db=True)
            except sqlite3.OperationalError:
                # if sqlite3.OperationalError, try in-memory database
                # Todo: store the db elsewhere if we don't have write access to this folder
                # This also makes it possible to run tests under pyfakefs since it can't patch sqlite3
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
        client.set_http_retry_params(retry=False, max_attempts=2, wait_exponential_multiplier=100)
        logger.info(client)
        return client

    def find_from_target(self, target: DicomWebTarget, accession: str, search_filters: Dict[str, List[str]] = {}
                         ) -> List[pydicom.Dataset]:
        super().find_from_target(target, accession, search_filters)
        client = self.create_client(target)
        use_filters = {'AccessionNumber': accession}

        # If there more one value per filter, just get metadata for the entire accession and filter it after.
        # Some DICOM servers do actually support filtering on lists, but DICOMwebClient does not seem to support this.
        # See: https://dicom.nema.org/medical/dicom/current/output/html/part18.html#sect_8.3.4.6
        for filter_values in search_filters.values():
            if len(filter_values) > 1:
                break
        else:
            use_filters.update({k: v[0] for k, v in search_filters.items()})

        metadata = client.search_for_series(search_filters=use_filters, get_remaining=True,
                                            fields=['StudyInstanceUID',
                                                    'SeriesInstanceUID',
                                                    'NumberOfSeriesRelatedInstances',
                                                    'StudyDescription', 'SeriesDescription'] + list(search_filters.keys()))
        meta_datasets = [pydicom.Dataset.from_json(ds) for ds in metadata]
        result = []

        # In case the server didn't filter as strictly as we expected it to, filter again
        for d in meta_datasets:
            for filter in search_filters:
                if d.get(filter) not in search_filters[filter]:
                    break
            else:
                result.append(d)
        logger.debug(result)
        return result

    def get_from_target(self, target: DicomWebTarget, accession, search_filters, destination_path: str
                        ) -> Generator[ProgressInfo, None, None]:
        series = self.find_from_target(target, accession, search_filters=search_filters)
        if not series:
            raise ValueError("No series found with accession number {}".format(accession))
        n = 0
        remaining = sum([int(x.NumberOfSeriesRelatedInstances) for x in series])
        client = self.create_client(target)
        for s in series:
            instances = client.retrieve_series(s.StudyInstanceUID, s.SeriesInstanceUID)
            # remaining += len(instances)
            for instance in instances:
                sop_instance_uid = instance.get('SOPInstanceUID')
                filename = f"{destination_path}/{sop_instance_uid}.dcm"
                instance.save_as(filename)
                n += 1
                remaining -= 1
                time.sleep(0.5)
                yield ProgressInfo(n, remaining, f'{n} / {n + remaining}')
        time.sleep(0.5)

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

        results: Dict[str, Union[bool, str, None]] = {}
        results["Authentication"] = None
        if isinstance(client, DICOMwebClient):
            try:
                client._http_get(target.url)
                results["Authentication"] = True
            except HTTPError as e:
                if e.errno == 401:
                    results["Authentication"] = False
                else:
                    results["Authentication"] = True
        elif isinstance(client, DICOMfileClient):
            folder = Path(target.url[7:])
            if not folder.exists() or not folder.is_dir():
                results["Authentication"] = f"No such folder {folder}"
            elif target.direction in ("pull", "both") and not os.access(folder, os.R_OK):
                results["Authentication"] = f"No read access to folder {folder}"
            elif target.direction in ("push", "both") and not os.access(folder, os.W_OK):
                results["Authentication"] = f"No write access to folder {folder}"
            else:
                results["Authentication"] = True
        try:
            client.search_for_studies(limit=1)
            results["QIDO query"] = True
        except HTTPError:
            results["QIDO query"] = False

        return results
