"""
types.py
========
Definitions for using TypedDicts throughout mercure.
"""

# Standard python includes
from typing import Dict, List, Optional, Union
from typing_extensions import Literal, TypedDict


# TODO: Add description for the individual classes


class Target(TypedDict, total=False):
    ip: str
    port: str
    aet_target: str
    aet_source: str
    contact: str


class Module(TypedDict, total=False):
    url: str
    docker_tag: str
    additional_volumes: str
    environment: str
    docker_arguments: str


class UnsetRule(TypedDict):
    rule: str


class Rule(TypedDict, total=False):
    rule: str
    target: str
    disabled: Literal["True", "False"]
    fallback: str
    contact: str
    comment: str
    tags: str
    action: Literal["route", "both", "process", "discard", "notification"]
    action_trigger: Literal["series", "study"]
    study_trigger_condition: Literal["timeout", "received_series"]
    study_trigger_series: str
    priority: Literal["normal", "urgent", "offpeak"]
    processing_module: str
    processing_settings: str
    notification_webhook: str
    notification_payload: str
    notification_trigger_reception: Literal["True", "False"]
    notification_trigger_completion: Literal["True", "False"]
    notification_trigger_error: Literal["True", "False"]


class Config(TypedDict):
    appliance_name: str
    port: int
    incoming_folder: str
    studies_folder: str
    outgoing_folder: str
    success_folder: str
    error_folder: str
    discard_folder: str
    processing_folder: str
    router_scan_interval: int  # in seconds
    dispatcher_scan_interval: int  # in seconds
    cleaner_scan_interval: int  # in seconds
    retention: int  # in seconds (3 days)
    retry_delay: int  # in seconds (15 min)
    retry_max: int
    series_complete_trigger: int  # in seconds
    study_complete_trigger: int  # in seconds
    study_forcecomplete_trigger: int  # in seconds
    graphite_ip: str
    graphite_port: int
    bookkeeper: str
    offpeak_start: str
    offpeak_end: str
    targets: Dict[str, Target]
    rules: Dict[str, Rule]
    modules: Dict[str, Module]
    process_runner: Literal["docker", "nomad"]


class TaskInfo(TypedDict, total=False):
    action: Literal["route", "both", "process", "discard", "notification"]
    uid: str
    uid_type: Literal["series", "study"]
    triggered_rules: Union[Dict[str, Literal[True]], str]
    applied_rule: str
    mrn: str
    acc: str
    mercure_version: str
    mercure_appliance: str
    mercure_server: str


class TaskDispatch(TypedDict, total=False):
    target_name: str
    target_ip: str
    target_port: str
    target_aet_target: str
    target_aet_source: str
    retries: Optional[int]
    next_retry_at: Optional[float]


class TaskStudy(TypedDict):
    study_uid: str
    complete_trigger: str
    complete_required_series: str
    creation_time: str
    last_receive_time: str
    received_series: Optional[List]
    complete_force: Literal["True", "False"]


class EmptyDict(TypedDict):
    pass


class Task(TypedDict):
    info: TaskInfo
    dispatch: Union[TaskDispatch, EmptyDict]
    process: Union[Module, EmptyDict]
    study: Union[TaskStudy, EmptyDict]

class TaskHasStudy(TypedDict):
    info: TaskInfo
    dispatch: Union[TaskDispatch, EmptyDict]
    process: Union[Module, EmptyDict]
    study: TaskStudy
