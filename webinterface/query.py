import os
import re
from typing import Any, Iterator, List, Optional, Sequence, cast
from pynetdicom import (
        AE,
        QueryRetrievePresentationContexts, BasicWorklistManagementPresentationContexts, UnifiedProcedurePresentationContexts,
        build_role,
        evt,
        StoragePresentationContexts
    )
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind # type: ignore
from pynetdicom.apps.common import create_dataset
from pynetdicom._globals import DEFAULT_MAX_LENGTH
from pynetdicom.pdu_primitives import SOPClassExtendedNegotiation
from pynetdicom.sop_class import (  # type: ignore
    PatientRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelGet,
    PatientStudyOnlyQueryRetrieveInformationModelGet,
    EncapsulatedSTLStorage,
    EncapsulatedOBJStorage,
    EncapsulatedMTLStorage,
)
from pydicom.uid import DeflatedExplicitVRLittleEndian 
from pydicom import Dataset
import sys
import subprocess

class DicomClientCouldNotAssociate(Exception):
    pass

class DicomClientCouldNotFind(Exception):
    pass

class DicomClientBadStatus(Exception):
    pass

SOP_CLASS_PREFIXES = {
    "1.2.840.10008.5.1.4.1.1.2": ("CT", "CT Image Storage"),
    "1.2.840.10008.5.1.4.1.1.2.1": ("CTE", "Enhanced CT Image Storage"),
    "1.2.840.10008.5.1.4.1.1.4": ("MR", "MR Image Storage"),
    "1.2.840.10008.5.1.4.1.1.4.1": ("MRE", "Enhanced MR Image Storage"),
    "1.2.840.10008.5.1.4.1.1.128": ("PT", "Positron Emission Tomography Image Storage"),
    "1.2.840.10008.5.1.4.1.1.130": ("PTE", "Enhanced PET Image Storage"),
    "1.2.840.10008.5.1.4.1.1.481.1": ("RI", "RT Image Storage"),
    "1.2.840.10008.5.1.4.1.1.481.2": ("RD", "RT Dose Storage"),
    "1.2.840.10008.5.1.4.1.1.481.5": ("RP", "RT Plan Storage"),
    "1.2.840.10008.5.1.4.1.1.481.3": ("RS", "RT Structure Set Storage"),
    "1.2.840.10008.5.1.4.1.1.1": ("CR", "Computed Radiography Image Storage"),
    "1.2.840.10008.5.1.4.1.1.6.1": ("US", "Ultrasound Image Storage"),
    "1.2.840.10008.5.1.4.1.1.6.2": ("USE", "Enhanced US Volume Storage"),
    "1.2.840.10008.5.1.4.1.1.12.1": ("XA", "X-Ray Angiographic Image Storage"),
    "1.2.840.10008.5.1.4.1.1.12.1.1": ("XAE", "Enhanced XA Image Storage"),
    "1.2.840.10008.5.1.4.1.1.20": ("NM", "Nuclear Medicine Image Storage"),
    "1.2.840.10008.5.1.4.1.1.7": ("SC", "Secondary Capture Image Storage"),
}
class SimpleDicomClient():
    host: str
    port: int
    called_aet: str
    output_dir: str
    def __init__(self, host, port, called_aet, out_dir) -> None:
        self.host = host
        self.port = int(port)
        self.called_aet = called_aet
        self.output_dir = out_dir
    
    def handle_store(self, event):
        try:
            ds = event.dataset
            # Remove any Group 0x0002 elements that may have been included
            ds = ds[0x00030000:]
        except Exception as exc:
            print(exc)
            return 0x210
        try:
            sop_class = ds.SOPClassUID
            # sanitize filename by replacing all illegal characters with underscores
            sop_instance = re.sub(r"[^\d.]", "_", ds.SOPInstanceUID)
        except Exception as exc:
            print(
                "Unable to decode the received dataset or missing 'SOP Class "
                "UID' and/or 'SOP Instance UID' elements"
            )
            print(exc)
            # Unable to decode dataset
            return 0xC210

        try:
            # Get the elements we need
            mode_prefix = SOP_CLASS_PREFIXES[sop_class][0]
        except KeyError:
            mode_prefix = "UN"

        filename = f"{self.output_dir}/{mode_prefix}.{sop_instance}.dcm"
        print(f"Storing DICOM file: {filename}")

        status_ds = Dataset()
        status_ds.Status = 0x0000
        try:
            if event.context.transfer_syntax == DeflatedExplicitVRLittleEndian:
                # Workaround for pydicom issue #1086
                with open(filename, "wb") as f:
                    f.write(event.encoded_dataset())
            else:
                # We use `write_like_original=False` to ensure that a compliant
                #   File Meta Information Header is written
                ds.save_as(filename, write_like_original=False)

            status_ds.Status = 0x0000  # Success
        except OSError as exc:
            print("Could not write file to specified directory:")
            print(f"    {os.path.dirname(filename)}")
            print(exc)
            # Failed - Out of Resources - OSError
            status_ds.Status = 0xA700
        except Exception as exc:
            print("Could not write file to specified directory:")
            print(f"    {os.path.dirname(filename)}")
            print(exc)
            # Failed - Out of Resources - Miscellaneous error
            status_ds.Status = 0xA701

        subprocess.run(["./bin/ubuntu22.04/getdcmtags", filename, self.called_aet, "MERCURE"],check=True)
        return status_ds


    def getscu(self, accession_number) -> Iterator[Dataset]:
        # Exclude these SOP Classes
        _exclusion = [
            EncapsulatedSTLStorage,
            EncapsulatedOBJStorage,
            EncapsulatedMTLStorage,
        ]
        store_contexts = [
            cx for cx in StoragePresentationContexts if cx.abstract_syntax not in _exclusion
        ]
        ae = AE(ae_title="MERCURE")
        # Create application entity
        # Binding to port 0 lets the OS pick an available port
        ae.acse_timeout = 30
        ae.dimse_timeout = 30
        ae.network_timeout = 30
        ae.add_requested_context(PatientRootQueryRetrieveInformationModelGet)
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        ae.add_requested_context(PatientStudyOnlyQueryRetrieveInformationModelGet)
        ext_neg = []
        for cx in store_contexts:
            if not cx.abstract_syntax:
                raise ValueError(f"Abstract syntax must be specified for storage context {cx}")
            ae.add_requested_context(cx.abstract_syntax)
            # Add SCP/SCU Role Selection Negotiation to the extended negotiation
            # We want to act as a Storage SCP
            ext_neg.append(build_role(cx.abstract_syntax, scp_role=True))
        query_model = StudyRootQueryRetrieveInformationModelGet
        assoc = ae.associate(
                self.host, self.port,
                ae_title=self.called_aet,
                ext_neg=ext_neg, # type: ignore
                evt_handlers=[(evt.EVT_C_STORE, self.handle_store, [])],
                max_pdu=0,
            )
        if not assoc.is_established:
            raise DicomClientCouldNotAssociate()
            # Send query

        ds = Dataset()
        ds.QueryRetrieveLevel = 'STUDY'
        ds.AccessionNumber = accession_number

        responses = assoc.send_c_get(ds, query_model)
        success = False
        for status, rsp_identifier in responses:
            # If `status.Status` is one of the 'Pending' statuses then
            #   `rsp_identifier` is the C-GET response's Identifier dataset
            if not status:
                raise DicomClientBadStatus()
            
            if status.Status in [0xFF00, 0xFF01]:
                yield status
                success = True
        if not success:
            raise DicomClientCouldNotFind()

        assoc.release()

    def findscu(self,accession_number) -> List[Dataset]:
        # Create application entity
        ae = AE(ae_title="MERCURE")

        # Add a requested presentation context
        # ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        ae.requested_contexts = QueryRetrievePresentationContexts
                # + BasicWorklistManagementPresentationContexts
                # + UnifiedProcedurePresentationContexts )

        # Associate with the peer AE
        assoc = ae.associate(self.host, self.port, ae_title=self.called_aet, max_pdu=0, ext_neg=[])

        ds = Dataset()
        ds.QueryRetrieveLevel = 'STUDY'
        ds.AccessionNumber = accession_number
        if not assoc.is_established:
            raise DicomClientCouldNotAssociate()

        try:
            responses = assoc.send_c_find(
                ds,
                StudyRootQueryRetrieveInformationModelFind
            )
            results = []
            for (status, identifier) in responses:
                if not status:
                    print('Connection timed out, was aborted or received invalid response')
                    break

                if status.Status in [0xFF00, 0xFF01]:
                    # print('C-FIND query status: 0x{0:04x}'.format(status.Status))
                    results.append(identifier)
                # elif status.Status == 0x0000:
                #     print("Success")
                #     break
            if not results:
                raise DicomClientCouldNotFind()
            return results
        finally:
            assoc.release()

if __name__ == "__main__":
    # Replace these variables with your actual values
    remote_host = sys.argv[1]
    remote_port = int(sys.argv[2])
    calling_aet = sys.argv[3]
    called_aet = sys.argv[4]
    accession_number = sys.argv[5]

    print(f"{remote_host=} {remote_port=} {calling_aet=} {called_aet=} {accession_number=}")
    c = SimpleDicomClient(remote_host, remote_port, called_aet, "/tmp/test-move")
    # study_uid = c.get_study_uid(accession_number)
    # print(study_uid)
    c.getscu(accession_number)