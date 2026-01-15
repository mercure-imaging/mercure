"""
dicomweb.py
===========
"""

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Generator, List, Union

import common.config as config
import pydicom
from common.types import DicomWebTarget, Task, TaskDispatch
from dicomweb_client import DICOMfileClient
from dicomweb_client.api import DICOMwebClient
from dicomweb_client.session_utils import create_session_from_user_pass
from requests.exceptions import HTTPError
import requests

from .base import ProgressInfo, TargetHandler
from .registry import handler_for

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

        # Priority order for authentication:
        # 1. GCP Service Account (if configured)
        # 2. HTTP Basic Auth
        # 3. Bearer Token

        if target.gcp_service_account_json_path:
            session = self._create_gcp_authenticated_session(target)
        elif target.http_user and target.http_password:
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

    ### New Helper method:
    def _create_gcp_authenticated_session(self, target: DicomWebTarget) -> requests.Session:
        """
        Create a requests Session authenticated with GCP service account credentials.
        
        Args:
            target: DicomWebTarget with GCP service account configuration
            
        Returns:
            Authenticated requests.Session object
            
        Raises:
            FileNotFoundError: If service account JSON file doesn't exist
            ValueError: If service account JSON is invalid
            google.auth.exceptions.GoogleAuthError: For authentication errors
        """
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        
        # Validate file exists
        json_path = Path(target.gcp_service_account_json_path)
        if not json_path.exists():
            raise FileNotFoundError(
                f"GCP service account JSON file not found: {json_path}"
            )
        
        # Default scopes for Cloud Healthcare API
        scopes = target.gcp_auth_scopes or [
            'https://www.googleapis.com/auth/cloud-healthcare'
        ]
        
        logger.info(f"Loading GCP service account credentials from: {json_path}")
        
        try:
            # Load credentials from service account JSON
            credentials = service_account.Credentials.from_service_account_file(
                str(json_path),
                scopes=scopes
            )
            
            # Create an authorized session
            # This session will automatically refresh tokens as needed
            session = AuthorizedSession(credentials)
            
            logger.info("GCP service account authentication configured successfully")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create GCP authenticated session: {e}")
            raise ValueError(
                f"Invalid GCP service account JSON or authentication error: {e}"
            )

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
        # Clear empty string fields (existing logic)
        for x in [
            "qido_url_prefix",
            "wado_url_prefix",
            "stow_url_prefix",
            "http_user",
            "http_password",
            "access_token",
            "gcp_service_account_json_path",  # NEW
            "gcp_auth_scopes",                # NEW
        ]:
            if x in form and not form[x]:
                form[x] = None
        
        # Parse gcp_auth_scopes if provided as comma-separated string
        if "gcp_auth_scopes" in form and form["gcp_auth_scopes"]:
            if isinstance(form["gcp_auth_scopes"], str):
                form["gcp_auth_scopes"] = [
                    s.strip() for s in form["gcp_auth_scopes"].split(",")
                ]
        
        return DicomWebTarget(**form)

    async def test_connection(self, target: DicomWebTarget, target_name: str):
        client = self.create_client(target)
        
        results: Dict[str, Union[bool, str, None]] = {}
        results["Authentication"] = None
        
        # File-based client testing (unchanged)
        if isinstance(client, DICOMfileClient):
            folder = Path(target.url[7:])
            if not folder.exists() or not folder.is_dir():
                results["Authentication"] = f"No such folder {folder}"
            elif target.direction in ("pull", "both") and not os.access(folder, os.R_OK):
                results["Authentication"] = f"No read access to folder {folder}"
            elif target.direction in ("push", "both") and not os.access(folder, os.W_OK):
                results["Authentication"] = f"No write access to folder {folder}"
            else:
                results["Authentication"] = True
        
        # HTTP-based client testing
        elif isinstance(client, DICOMwebClient):
            try:
                # Test authentication
                client._http_get(target.url)
                results["Authentication"] = True
                
                # Add authentication method info for debugging
                if target.gcp_service_account_json_path:
                    results["Auth Method"] = "GCP Service Account"
                elif target.http_user:
                    results["Auth Method"] = "HTTP Basic Auth"
                elif target.access_token:
                    results["Auth Method"] = "Bearer Token"
                else:
                    results["Auth Method"] = "None"
                    
            except HTTPError as e:
                if e.response.status_code == 401:
                    results["Authentication"] = False
                    results["Error"] = "Authentication failed (401 Unauthorized)"
                elif e.response.status_code == 403:
                    results["Authentication"] = False
                    results["Error"] = "Access forbidden (403 Forbidden)"
                else:
                    # Other errors might not be auth-related
                    results["Authentication"] = True
                    results["Warning"] = f"HTTP {e.response.status_code}"
            except Exception as e:
                results["Authentication"] = f"Error: {str(e)}"
        
        # Test QIDO query capability
        try:
            client.search_for_studies(limit=1)
            results["QIDO query"] = True
        except HTTPError as e:
            results["QIDO query"] = False
            results["QIDO Error"] = f"HTTP {e.response.status_code}"
        except Exception as e:
            results["QIDO query"] = False
            results["QIDO Error"] = str(e)
        
        return results
