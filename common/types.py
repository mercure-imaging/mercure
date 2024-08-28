"""
types.py
========
Definitions for using TypedDicts throughout mercure.
"""

# Standard python includes
from typing import Any, Dict, List, Optional, Type, Union, cast
from typing_extensions import Literal, TypedDict
from pydantic import BaseModel
import typing

# TODO: Add description for the individual classes


class Compat:
    def get(self, item, els=None) -> Any:
        return self.__dict__.get(item, els) or els


class EmptyDict(TypedDict):
    pass

class Target(BaseModel, Compat):
    target_type: Any
    contact: Optional[str] = ""
    comment: str = ""

    @classmethod
    def __get_validators__(cls):
        # one or more validators may be yielded which will be called in the
        # order to validate the input, each validator will receive as an input
        # the value returned from the previous validator
        yield cls.validate

    @classmethod
    def validate(cls, v):
        """Parse the target as any of the known target types."""

        subclass_dict: typing.Dict[str, Type[Target]] = {sbc.__name__: sbc for sbc in cls.__subclasses__()}

        for k in subclass_dict:
            try:
                return subclass_dict[k](**v)
            except:
                pass

        raise ValueError("Couldn't validate target as any of", list(subclass_dict.keys()))

    @classmethod
    def get_name(cls) -> str:
        return cls.construct().target_type  # type: ignore


class DicomTarget(Target):
    target_type: Literal["dicom"] = "dicom"
    ip: str
    port: str
    aet_target: str
    aet_source: Optional[str] = ""


class DicomTLSTarget(Target):
    target_type: Literal["dicomtls"] = "dicomtls"
    ip: str
    port: str
    aet_target: str
    aet_source: Optional[str] = ""
    tls_key: str
    tls_cert: str
    ca_cert: str


class SftpTarget(Target):
    target_type: Literal["sftp"] = "sftp"
    folder: str
    user: str
    host: str
    password: Optional[str]


class RsyncTarget(Target):
    target_type: Literal["rsync"] = "rsync"
    folder: str
    user: str
    host: str
    password: Optional[str]
    run_on_complete: bool = False


class XnatTarget(Target):
    target_type: Literal["xnat"] = "xnat"
    project_id: str
    host: str
    user: str
    password: str


class DicomWebTarget(Target):
    target_type: Literal["dicomweb"] = "dicomweb"
    url: str
    qido_url_prefix: Optional[str] = None
    wado_url_prefix: Optional[str] = None
    stow_url_prefix: Optional[str] = None
    access_token: Optional[str] = None
    http_user: Optional[str] = None
    http_password: Optional[str] = None


class S3Target(Target):
    target_type: Literal["s3"] = "s3"
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    secret_access_key: str


class FolderTarget(Target):
    target_type: Literal["folder"] = "folder"
    folder: str


class DummyTarget(Target):
    target_type: Literal["dummy"] = "dummy"


class Module(BaseModel, Compat):
    docker_tag: Optional[str] = ""
    additional_volumes: Optional[str] = ""
    environment: Optional[str] = ""
    docker_arguments: Optional[str] = ""
    settings: Dict[str, Any] = {}
    contact: Optional[str] = ""
    comment: Optional[str] = ""
    constraints: Optional[str] = ""
    resources: Optional[str] = ""
    requires_root: Optional[bool] = False


class UnsetRule(TypedDict):
    rule: str


class Rule(BaseModel, Compat):
    rule: str = "False"
    target: str = ""
    disabled: bool = False
    fallback: bool = False
    contact: str = ""
    comment: str = ""
    tags: str = ""
    action: Literal["route", "both", "process", "discard", "notification"] = "route"
    action_trigger: Literal["series", "study"] = "series"
    study_trigger_condition: Literal["timeout", "received_series"] = "timeout"
    study_trigger_series: str = ""
    priority: Literal["normal", "urgent", "offpeak"] = "normal"
    processing_module: Union[str,List[str]] = ""
    processing_settings: Union[List[Dict[str, Any]],Dict[str, Any]] = {}
    processing_retain_images: bool = False
    notification_email: str = ""
    notification_webhook: str = ""
    notification_payload: str = ""
    notification_payload_body: str = ""
    notification_email_body: str = ""
    notification_email_type: str = "plain"
    notification_trigger_reception: bool = True
    notification_trigger_completion: bool = True
    notification_trigger_completion_on_request: bool = False
    notification_trigger_error: bool = True


class ProcessingLogsConfig(BaseModel):
    discard_logs: bool = False
    logs_file_store: Optional[str] = None


class DicomReceiverConfig(BaseModel):
    additional_tags: Dict[str,str] = {}


class DicomNodeBase(BaseModel):
    name: str

    @classmethod
    def __get_validators__(cls):
        # one or more validators may be yielded which will be called in the
        # order to validate the input, each validator will receive as an input
        # the value returned from the previous validator
        yield cls.validate

    @classmethod
    def validate(cls, v):
        """Parse the target as any of the known target types."""
        subclass_dict: typing.Dict[str, Type[DicomNodeBase]] = {sbc.__name__: sbc for sbc in cls.__subclasses__()}
        for k in subclass_dict:
            try:
                return subclass_dict[k](**v)
            except:
                pass
        raise ValueError("Couldn't validate dicom node as any of", list(subclass_dict.keys()))

    @classmethod
    def get_name(cls) -> str:
        return cls.construct().node_type  # type: ignore

class DicomDestination(BaseModel):
    name: str
    path: str

class DicomRetrieveConfig(BaseModel):
    dicom_nodes: List[DicomNodeBase] = []
    destination_folders: List[DicomDestination] = []
    
class Config(BaseModel, Compat):
    appliance_name: str
    port: int
    accept_compressed_images: bool
    incoming_folder: str
    studies_folder: str
    outgoing_folder: str
    success_folder: str
    error_folder: str
    discard_folder: str
    processing_folder: str
    jobs_folder: str
    router_scan_interval: int       # in seconds
    dispatcher_scan_interval: int   # in seconds
    cleaner_scan_interval: int      # in seconds
    retention: int                  # in seconds (3 days)
    emergency_clean_percentage: int # in % of disk space
    retry_delay: int                # in seconds (15 min)
    retry_max: int
    series_complete_trigger: int    # in seconds
    study_complete_trigger: int     # in seconds
    study_forcecomplete_trigger: int  # in seconds
    dicom_receiver: DicomReceiverConfig = DicomReceiverConfig()
    graphite_ip: str
    graphite_port: int
    influxdb_host: str
    influxdb_token: str
    influxdb_org: str
    influxdb_bucket: str
    bookkeeper: str
    offpeak_start: str
    offpeak_end: str
    targets: Dict[str, Target]
    rules: Dict[str, Rule]
    modules: Dict[str, Module]
    process_runner: Literal["docker", "nomad", ""] = ""
    processing_runtime: Optional[str] = None
    bookkeeper_api_key: Optional[str]
    features: Dict[str, bool]
    processing_logs: ProcessingLogsConfig = ProcessingLogsConfig()
    email_notification_from: str = "mercure@mercure.mercure"
    support_root_modules: Optional[bool] = False
    webhook_certificate_location: Optional[str] = None
    phi_notifications: Optional[bool] = False
    server_time: str = "UTC"
    local_time: str = "UTC"
    dicom_retrieve: DicomRetrieveConfig = DicomRetrieveConfig()

class TaskInfo(BaseModel, Compat):
    action: Literal["route", "both", "process", "discard", "notification"]
    uid: str
    uid_type: Literal["series", "study"]
    triggered_rules: Union[Dict[str, Literal[True]], str]
    applied_rule: Optional[str]
    patient_name: Optional[str]
    mrn: str
    acc: str
    sender_address: str = "MISSING"
    mercure_version: str
    mercure_appliance: str
    mercure_server: str
    device_serial_number: Optional[str] = None


class TaskDispatch(BaseModel, Compat):
    target_name: str
    retries: Optional[int] = 0
    next_retry_at: Optional[float] = 0
    series_uid: Optional[str]


class TaskStudy(BaseModel, Compat):
    study_uid: str
    complete_trigger: Optional[str]
    complete_required_series: str
    creation_time: str
    last_receive_time: str
    received_series: Optional[List[str]]
    received_series_uid: Optional[List[str]]
    complete_force: bool = False


class TaskProcessing(BaseModel, Compat):
    module_name: str
    module_config: Optional[Module]
    settings: Dict[str, Any] = {}
    retain_input_images: bool
    output: Optional[Dict]

# class PydanticFile(object):
#     def __init__(self, klass, file_name):
#         self.Klass = klass
#         self.file_name = file_name

#     def __enter__(self):
#         self.file = open(self.file_name, "r+")
#         self.dict_orig = json.load(self.file)
#         self.file.seek(0)
#         self.obj = self.Klass(**self.dict_orig)
#         return self.obj

#     def __exit__(self, type, value, traceback):
#         new_dict = self.obj.dict()
#         if new_dict != self.dict_orig:
#             json.dump(new_dict, self.file)
#         self.file.truncate()
#         self.file.close()


# class ModelHasFile(object):
#     @classmethod
#     def file_editor(cls, file_name):
#         return PydanticFile(cls, file_name)


class Task(BaseModel, Compat):
    info: TaskInfo
    id: str
    dispatch: Union[TaskDispatch, EmptyDict] = cast(EmptyDict, {})
    process: Union[TaskProcessing, EmptyDict,List[TaskProcessing]] = cast(EmptyDict, {})
    study: Union[TaskStudy, EmptyDict] = cast(EmptyDict, {})
    nomad_info: Optional[Any]

    class Config:
        extra = "forbid"


class TaskHasStudy(Task):
    study: TaskStudy
