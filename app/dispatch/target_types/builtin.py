"""
builtin.py
==========
"""

from pathlib import Path
from shlex import split
from typing import Dict, Generator, List

import common.config as config
from common.constants import mercure_names
from common.types import DicomTarget, DicomTLSTarget, DummyTarget, SftpTarget, Task
from dispatch.process_dcmsend_result import parse as parse_dcmsend_result
from pydicom import Dataset
from webinterface.common import async_run
from webinterface.dicom_client import DicomClientCouldNotFind, SimpleDicomClient

from .base import ProgressInfo, SubprocessTargetHandler, TargetHandler
from .registry import handler_for

DCMSEND_ERROR_CODES = {
    1: "EXITCODE_COMMANDLINE_SYNTAX_ERROR",
    21: "EXITCODE_NO_INPUT_FILES",
    22: "EXITCODE_INVALID_INPUT_FILE",
    23: "EXITCODE_NO_VALID_INPUT_FILES",
    43: "EXITCODE_CANNOT_WRITE_REPORT_FILE",
    60: "EXITCODE_CANNOT_INITIALIZE_NETWORK",
    61: "EXITCODE_CANNOT_NEGOTIATE_ASSOCIATION",
    62: "EXITCODE_CANNOT_SEND_REQUEST",
    65: "EXITCODE_CANNOT_ADD_PRESENTATION_CONTEXT",
}
logger = config.get_logger()


@handler_for(DicomTarget)
class DicomTargetHandler(SubprocessTargetHandler[DicomTarget]):
    view_template = "targets/dicom.html"
    edit_template = "targets/dicom-edit.html"
    test_template = "targets/dicom-test.html"
    icon = "fa-database"
    display_name = "DICOM"
    can_pull = True

    def _create_command(self, target: DicomTarget, source_folder: Path, task: Task):
        target_ip = target.ip
        if target_ip == "sender":
            # If results should be looped back to the original sender of the task, insert
            # the IP/address obtained from the DICOM receiver
            target_ip = task.info.sender_address
        if not target_ip:
            # If not target ip has been provided, insert a value that allows identifying the issue
            target_ip = "target_missing"

        target_port = target.port or 104
        target_aet_target = target.aet_target or ""
        target_aet_source = target.aet_source or ""

        if target.pass_sender_aet:
            target_aet_source = task.info.sender_aet
        if target.pass_receiver_aet:
            target_aet_target = task.info.receiver_aet

        dcmsend_status_file = str(Path(source_folder) / mercure_names.SENDLOG)
        command = split(
            (f"""dcmsend {target_ip} {target_port} +sd {source_folder} -aet {target_aet_source} """
             f"""-aec {target_aet_target} -nuc +sp '*.dcm' -to 60 +crf {dcmsend_status_file}""")
        )
        return command, {}

    def find_from_target(self, target: DicomTarget, accession: str, search_filters: Dict[str, List[str]]) -> List[Dataset]:
        c = SimpleDicomClient(target.ip, target.port, target.aet_target, target.aet_source, None)
        try:
            return c.findscu(accession, search_filters)
        except DicomClientCouldNotFind:
            return []

    def get_from_target(self, target: DicomTarget, accession: str,
                        search_filters: Dict[str, List[str]], destination_path: str) -> Generator[ProgressInfo, None, None]:
        config.read_config()
        c = SimpleDicomClient(target.ip, target.port, target.aet_target, target.aet_source, destination_path)
        for identifier in c.getscu(accession, search_filters):
            completed, remaining = (identifier.NumberOfCompletedSuboperations, identifier.NumberOfRemainingSuboperations)
            progress = f"{ completed } / { completed + remaining }"
            yield ProgressInfo(completed, remaining, progress)

    def handle_error(self, e, command):
        dcmsend_error_message = DCMSEND_ERROR_CODES.get(e.returncode, None)
        logger.exception(f"Failed command:\n {command} \nbecause of {dcmsend_error_message}")
        raise RuntimeError(f"{dcmsend_error_message}")

    def subprocess_success_check(self, command: list) -> None:
        result_file = Path(command[-1])
        if result_file.exists():
            parsed_result = parse_dcmsend_result(result_file)
            logger.info(f"dcmsend result: {parsed_result}")
            total_instances = parsed_result["summary"].get("sop_instances", 0)
            success_instances = parsed_result["summary"].get("successful", 0)
            if total_instances != success_instances:
                raise RuntimeError(
                    f"Only {success_instances} out of {total_instances} instances were sent successfully."
                )
        else:
            raise RuntimeError(f"Result file {result_file} from dcmsend not found.")

    async def test_connection(self, target: DicomTarget, target_name: str):
        cecho_response = False
        ping_response = False
        loopback_mode = False

        target_ip = target.ip or ""
        target_port = target.port or ""
        target_aec = target.aet_target or "ANY-SCP"
        target_aet = target.aet_source or "ECHOSCU"

        if target_ip == "sender":
            loopback_mode = True

        logger.info(f"Testing target {target_name}")

        if target_ip and target_port and not loopback_mode:
            ping_result, *_ = await async_run(f"ping -w 1 -c 1 {target_ip}")
            if ping_result == 0:
                ping_response = True

            cecho_result, *_ = await async_run(
                f"echoscu -to 2 -aec {target_aec} -aet {target_aet} {target_ip} {target_port}"
            )
            if cecho_result == 0:
                cecho_response = True

        return {"ping": ping_response, "c-echo": cecho_response, "loopback_mode": loopback_mode}


@handler_for(DicomTLSTarget)
class DicomTLSTargetHandler(SubprocessTargetHandler[DicomTLSTarget]):
    view_template = "targets/dicom-tls.html"
    edit_template = "targets/dicom-tls-edit.html"
    test_template = "targets/dicom-test.html"
    icon = "fa-database"
    display_name = "DICOM+TLS"

    def _create_command(self, target: DicomTLSTarget, source_folder: Path, task: Task):
        target_ip = target.ip
        target_port = target.port or 104
        target_aet_target = target.aet_target or ""
        target_aet_source = target.aet_source or ""

        if target.pass_sender_aet:
            target_aet_source = task.info.sender_aet
        if target.pass_receiver_aet:
            target_aet_target = task.info.receiver_aet

        command = split(
            f"""storescu +tls {target.tls_key} {target.tls_cert} +cf {target.ca_cert} {target_ip} {target_port} """
            f"""+sd {source_folder} -aet {target_aet_source} -aec {target_aet_target} +sp '*.dcm' -to 60"""
        )
        return command, {}

    def handle_error(self, e, command):
        dcmsend_error_message = DCMSEND_ERROR_CODES.get(e.returncode, None)
        logger.exception(f"Failed command:\n {command} \nbecause of {dcmsend_error_message}")
        raise RuntimeError(f"{dcmsend_error_message}")

    async def test_connection(self, target: DicomTLSTarget, target_name: str):
        cecho_response = False
        ping_response = False
        target_ip = target.ip or ""
        target_port = target.port or ""
        target_aec = target.aet_target or "ANY-SCP"
        target_aet = target.aet_source or "ECHOSCU"
        tls_key = target.tls_key
        tls_cert = target.tls_cert
        ca_cert = target.ca_cert

        logger.info(f"Testing TLS target {target_name}")

        if target_ip and target_port:
            ping_result, *_ = await async_run(f"ping -w 1 -c 1 {target_ip}")
            if ping_result == 0:
                ping_response = True

            cecho_command = (f"echoscu -to 2 -aec {target_aec} -aet {target_aet} {target_ip}"
                             f" {target_port} +tls {tls_key} {tls_cert} +cf {ca_cert}")
            logger.info('Running %s' % cecho_command)
            cecho_result, *_ = await async_run(cecho_command)
            if cecho_result == 0:
                cecho_response = True

        return {"ping": ping_response, "c-echo": cecho_response}


@handler_for(SftpTarget)
class SftpTargetHandler(SubprocessTargetHandler[SftpTarget]):
    view_template = "targets/sftp.html"
    edit_template = "targets/sftp-edit.html"
    test_template = "targets/sftp-test.html"
    icon = "fa-server"
    display_name = "SFTP"

    def _create_command(self, target: SftpTarget, source_folder: Path, task: Task):
        command = (
            "sftp -o StrictHostKeyChecking=no "
            + f""" "{target.user}@{target.host}:{target.folder}" """
            + f""" <<- EOF
                    mkdir "{target.folder}/{source_folder.stem}"
                    put -f -r "{source_folder}"
                    !touch "/tmp/.complete"
                    put -f "/tmp/.complete" "{target.folder}/{source_folder.stem}/.complete"
EOF"""
        )
        if target.password:
            command = f"sshpass -p {target.password} " + command
        return split(command), dict(shell=True, executable="/bin/bash")

    async def test_connection(self, target: SftpTarget, target_name: str):
        ping_response = False
        ping_result, *_ = await async_run(f"ping -w 1 -c 1 {target.host}")
        ping_response = True if ping_result == 0 else False
        response = False
        stderr = b""

        command = "sftp -o StrictHostKeyChecking=no " + f""" "{target.user}@{target.host}:{target.folder}" <<< "" """
        if target.password:
            command = f"sshpass -p {target.password} " + command
        logger.debug(command)
        result, stdout, stderr = await async_run(command, shell=True, executable="/bin/bash")
        response = True if result == 0 else False
        return dict(ping=ping_response, loggedin=response, err=stderr.decode("utf-8") if not response else "")


@handler_for(DummyTarget)
class DummyTargetHandler(TargetHandler):
    icon = "fa-flask"
    view_template = "targets/dummy.html"
    edit_template = "targets/dummy-edit.html"

    display_name = "Dummy"
