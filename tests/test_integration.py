import asyncore
from dataclasses import dataclass
import functools
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Generator, Optional
import pytest
import requests
from supervisor.supervisord import Supervisor
from supervisor.states import RUNNING_STATES
from supervisor.options import ServerOptions
from supervisor.xmlrpc import SupervisorTransport
import xmlrpc.client
import tempfile
from common.config import mercure_defaults
from common.types import FolderTarget, Module, Rule, Target
from tests.testing_common import create_minimal_dicom
import pydicom
from pynetdicom import AE
from pynetdicom.sop_class import MRImageStorage # type: ignore
import logging
import socket

# current workding directory
here = os.path.abspath(os.getcwd())

logging.getLogger('pynetdicom').setLevel(logging.WARNING)
def send_dicom(ds, dest_host, dest_port) -> Optional[pydicom.Dataset]:
    """
    Sends a DICOM Dataset to a specified destination using pynetdicom.

    Parameters:
        ds (pydicom.Dataset): The DICOM dataset to send.
        dest_host (str): The destination DICOM server hostname or IP.
        dest_port (int): The destination DICOM server port.

    Returns:
        status (pydicom.Dataset or None): The status dataset returned by the C-STORE request,
                                          or None if the association failed.
    """
    # Enable debug logging (optional)
    # debug_logger()

    # Create an AE (Application Entity) instance
    ae = AE()

    # Add a requested presentation context
    ae.add_requested_context(MRImageStorage)

    # Associate with the remote AE (DICOM server)
    assoc = ae.associate(dest_host, dest_port)

    if assoc.is_established:
        # Send the DICOM dataset
        status = assoc.send_c_store(ds)

        # Release the association
        assoc.release()

        # Return the status
        return status
    else:
        print("Failed to establish association")
        return None

class SupervisorManager:
    process: Optional[multiprocessing.Process] = None
    config_path: Optional[Path] = None
    def __init__(self, mercure_base: Path) -> None:
        self.mercure_base = mercure_base
        self.socket = mercure_base / "supervisor.sock"

    def create_config(self, services) -> None:
        self.config_path = self.mercure_base / 'supervisord.conf'
        log_path = self.mercure_base / 'supervisord.logs'
        pidfile = self.mercure_base / 'supervisord.pid'
        self.config_path.touch()

        with self.config_path.open('w') as f:
            f.write(f"""
[supervisord]
nodaemon=true
identifier=supervisor
directory=/tmp
loglevel=info
pidfile={pidfile}
sockfile={self.socket}
logfile={log_path}
[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface
[unix_http_server]
file={self.socket}
[supervisorctl]
serverurl=unix://{self.socket}
""")
            for service in services:
                f.write(f"""
[program:{service.name}]
command={service.command}
process_name=%(program_name)s{'_%(process_num)d' if service.numprocs>1 else ''}
directory=/opt/mercure/app
autostart=false
autorestart=false
redirect_stderr=true
startsecs={service.startsecs}
stopasgroup={str(service.stopasgroup).lower()}
numprocs={service.numprocs}
environment=MERCURE_CONFIG_FOLDER="{self.mercure_base}/config"
""")

    def run(self) -> None:
        args = ['-c', str(self.config_path)]
        options = ServerOptions()
        options.realize(args)
        
        s = Supervisor(options)
        options.first = True
        options.test = False
        try:
            s.main()
        except Exception as e:
            print(e)

    def start(self, services) -> None:
        self.create_config(services)
        self.process = multiprocessing.Process(target=self.run)
        self.process.start()
        self.wait_for_start()
        transport = SupervisorTransport(None, None, f'unix://{self.socket}')
        self.rpc = xmlrpc.client.ServerProxy('http://localhost', transport=transport)

    def start_service(self, name) -> None:
        self.rpc.supervisor.startProcess(name)

    def stop_service(self, name)-> None:
        self.rpc.supervisor.stopProcess(name)

    def all_services(self) -> Any:
        return self.rpc.supervisor.getAllProcessInfo() # type: ignore

    def get_service_log(self, name, offset=0, length=10000) -> Any:
        return self.rpc.supervisor.readProcessStdoutLog(name, offset, length) # type: ignore

    def stream_service_logs(self, name, timeout=1) -> None:
        offset = 0
        while True:
            log_data, offset, overflow = self.rpc.supervisor.tailProcessStdoutLog(name, offset, 1024) # type: ignore
            if log_data:
                print(log_data, end='', flush=True)
            if overflow:
                print(f"Warning: Log overflow detected for {name}. Some log entries may have been missed.")
            time.sleep(timeout)

    def stream_service_logs_threaded(self, name, timeout=1) -> threading.Thread:
        thread = threading.Thread(target=self.stream_service_logs, args=(name, timeout))
        thread.start()
        return thread
    def wait_for_start(self) -> None:
        while True:
            if Path(self.socket).exists():
                break
            else:
                time.sleep(0.1)
    def stop(self) -> None:
        if not self.process:
            return
        try:
            self.process.terminate()
            self.process.join()
        except asyncore.ExitNow:
            pass

@dataclass
class MercureService:
    name: str
    command: str
    numprocs: int = 1
    stopasgroup: bool = False
    startsecs: int = 0

def is_dicoms_received(mercure_base, dicoms) -> None:
    dicoms_recieved = set()
    for series_folder in (mercure_base / 'data' / 'incoming').glob('*/'):
        for dicom in series_folder.glob('*.dcm'):
            ds_ = pydicom.dcmread(dicom)
            assert ds_.SeriesInstanceUID == series_folder.name
            assert ds_.SOPInstanceUID not in dicoms_recieved
            dicoms_recieved.add(ds_.SOPInstanceUID) 
            
    assert dicoms_recieved == set(ds.SOPInstanceUID for ds in dicoms)
    print(f"Received {len(dicoms)} dicoms as expected")

def is_dicoms_in_folder(folder, dicoms) -> None:
    dicoms_found = set()
    for dicom in folder.glob('**/*.dcm'):
        uid = pydicom.dcmread(dicom).SOPInstanceUID
        dicoms_found.add(uid)
    try:
        assert dicoms_found == set(ds.SOPInstanceUID for ds in dicoms)
    except:
        print("Expected dicoms not found")
        for dicom in folder.glob('**/*.dcm'):
            print(dicom)
        raise
    print(f"Found {len(dicoms)} dicoms in {folder.name} as expected")

def is_series_registered(bookkeeper_port, dicoms) -> None:
    result = requests.get(f"http://localhost:{bookkeeper_port}/query/series",
                            headers={"Authorization": f"Token test"})
    assert result.status_code == 200
    result_json = result.json()
    assert set([r['series_uid'] for r in result_json]) == set([d.SeriesInstanceUID for d in dicoms])

@pytest.fixture(scope="function")
def supervisord(mercure_base):
    supervisor: Optional[SupervisorManager] = None
    def starter(services=[]):
        nonlocal supervisor
        if not supervisor:
            supervisor = SupervisorManager(mercure_base)
            supervisor.start(services)
            return supervisor
        return supervisor
    yield starter
    if supervisor is not None:
        supervisor.stop()


def stop_mercure(supervisor: SupervisorManager):
    logs = {}
    for service in supervisor.all_services():
        if service['state'] in RUNNING_STATES:
            try:
                supervisor.stop_service(service['name'])
            except xmlrpc.client.Fault as e:
                if e.faultCode == 10:
                    supervisor.stop_service(service['group']+":*")
        # log = get_service_log(service['name'])
        # if log:
        log =  Path(service['stdout_logfile']).read_text()
        if log:
            logs[service['name']] = log
    return logs

@pytest.fixture(scope="session")
def python_bin():
    if os.environ.get("CLEAN_VENV"):
        with tempfile.TemporaryDirectory(prefix="mercure_venv") as venvdir:
            subprocess.run([sys.executable, "-m", "venv", venvdir], check=True)
            subprocess.run([os.path.join(venvdir, "bin", "pip"), "install", "-r", f"{here}/requirements.txt"], check=True)
            yield venvdir+"/bin/python"
    else:
        yield sys.executable

@pytest.fixture(scope="function")
def mercure(mercure_base, supervisord: Callable[[Any], SupervisorManager], python_bin) -> Generator[Callable[[Any],SupervisorManager], None, None]:
    def py_service(service, **kwargs) -> MercureService:
        return MercureService(service,f"{python_bin} {here}/{service}.py", **kwargs)
    services = [
        py_service("bookkeeper",startsecs=10),
        py_service("router", numprocs=5),
        py_service("processor", numprocs=2),
        py_service("dispatcher", numprocs=5),
    ]
    services += [MercureService(f"receiver", f"{here}/receiver.sh", stopasgroup=True)]
    supervisor = supervisord(services)
    def do_start(services_to_start=["bookkeeper", "reciever", "router", "processor", "dispatcher"]) -> SupervisorManager:
        for service in services_to_start:
            supervisor.start_service(service)
        return supervisor
    yield do_start
    logs = stop_mercure(supervisor)
    for l in logs:
        print(f"====== {l} ======")
        print(logs[l])
    print("=============")

@pytest.fixture(scope="function")
def mercure_base() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory(prefix='mercure_') as temp_dir:
        temp_path = Path(temp_dir)
        for d in ['config','data']:
            (temp_path / d).mkdir()
        for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing"]:
            (temp_path / 'data' / k).mkdir()
        yield temp_path

def random_port() -> int:
    """
    Generate a free port number to use as an ephemeral endpoint.
    """
    s = socket.socket() 
    s.bind(('',0)) # bind to any available port
    port = s.getsockname()[1] # get the port number
    s.close()
    return int(port)


@pytest.fixture(scope="module")
def receiver_port():
    return random_port()

@pytest.fixture(scope="module")
def bookkeeper_port():
    return random_port()


@pytest.fixture(scope="function")
def mercure_config(mercure_base, receiver_port, bookkeeper_port):
    mercure_config = { k: v for k, v in mercure_defaults.items()}
    for folder in (mercure_base / 'data').iterdir():
        mercure_config[f"{folder.name}_folder"] = str(folder)

    mercure_config["series_complete_trigger"] = 1
    mercure_config["study_complete_trigger"] = 2
    mercure_config["bookkeeper_api_key"] = "test"
    mercure_config["port"] = receiver_port
    mercure_config["bookkeeper"] = f"localhost:{bookkeeper_port}"
    with (mercure_base / 'config' / 'mercure.json').open('w') as fp:
        json.dump(mercure_config, fp)

    bookkeeper_config = f"""
PORT={bookkeeper_port}
HOST=0.0.0.0
DATABASE_URL=sqlite:///{mercure_base}/data/bookkeeper.sqlite3
DEBUG=True
"""
    with (mercure_base / 'config' / 'bookkeeper.env').open('w') as fp:
        fp.write(bookkeeper_config)
    
    def update_config(config):
        with (mercure_base / 'config' / 'mercure.json').open('r+') as fp:
            data = json.load(fp)
            data.update(config)
            fp.seek(0)
            json.dump(data, fp)
            fp.truncate()
    return update_config

@pytest.mark.parametrize("n_series",(5,))
def test_case_simple(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="notification", action_trigger="series"
            ).dict(),
        }
    }
    mercure_config(config)
    supervisor = mercure(["receiver", "bookkeeper"])
    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Greg'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)
    time.sleep(2)
    is_dicoms_received(mercure_base, ds)
    supervisor.start_service("router:*")
    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "data" / "success", ds)
    is_series_registered(bookkeeper_port, ds)

@pytest.mark.parametrize("n_series",(5,))
def test_case_dispatch(mercure,mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="route", action_trigger="series", target="test_target"
            ).dict(),
        },
        "targets": {
            "test_target": FolderTarget(folder=str(mercure_base / "target")).dict()
        }
    }
    mercure_config(config)
    supervisor = mercure(["receiver", "router:*","bookkeeper"])
    (mercure_base / "target").mkdir(parents=True, exist_ok=True)

    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "data" / "outgoing", ds)
    
    supervisor.start_service("dispatcher:*")
    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "target", ds)
    is_series_registered(bookkeeper_port, ds)

    
@pytest.mark.parametrize("n_series",(3,))
def test_case_process(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="both", action_trigger="series", processing_module="dummy_module", target="test_target"
            ).dict(),
        },
        "modules": {
            "dummy_module": Module(
                docker_tag="mercureimaging/mercure-dummy-processor:latest"
            ).dict()
        },
        "targets": {
            "test_target": FolderTarget(folder=str(mercure_base / "target")).dict()
        }
    }
    mercure_config(config)
    mercure(["bookkeeper", "receiver", "router:*", "dispatcher:*", "processor:*"])
    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    for _ in range(220):
        try:
            is_dicoms_in_folder(mercure_base / "target", ds)
            break
        except AssertionError as e:
            time.sleep(1)
    else:
        raise Exception("Failed to find dicoms in target folder after 120 seconds.")
    is_series_registered(bookkeeper_port, ds)
    # t1.join(0.1)

