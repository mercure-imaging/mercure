import asyncore
from dataclasses import dataclass
import functools
import json
import multiprocessing
import os
from pathlib import Path
import time
import pytest
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
from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import MRImageStorage


here = os.path.abspath(os.path.dirname(__file__))
receiver_port = 21113
supervisor_process = None

def send_dicom(ds, dest_host, dest_port):
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


    # Send the dataset to a DICOM server (replace with your server's IP and port)
    status = send_dicom(ds, "127.0.0.1", 11112)

    if status:
        print(f"C-STORE request status: 0x{status.Status:04x}")
    else:
        print("DICOM file sending failed")


def create_supervisor_config(services, mercure_base):
    config_fd, config_path = tempfile.mkstemp(prefix='mercure_supervisord_conf')    
    log_fd, log_path = tempfile.mkstemp(prefix='mercure_supervisord_log')
    with open(config_fd, 'w') as f:
        f.write(f"""
[supervisord]
nodaemon=true
identifier=supervisor
directory=/tmp
loglevel=info
pidfile=/tmp/supervisord.pid
sockfile=/tmp/supervisor.sock
logfile={log_path}

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[unix_http_server]
file=/tmp/supervisor.sock

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

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
environment=MERCURE_CONFIG_FOLDER="{mercure_base}/config"
""")

    return config_path

def run_supervisor(config_path):
    args = ['-c', config_path]
    options = ServerOptions()
    options.realize(args)
    
    s = Supervisor(options)
    options.first = True
    options.test = False
    try:
        s.main()
    except Exception as e:
        print(e)
        pass

def start_supervisor(services, mercure_base):
    config_path = create_supervisor_config(services, mercure_base)
    process = multiprocessing.Process(target=run_supervisor, args=(config_path,))
    process.start()
    wait_for_supervisor()
    return process

def get_supervisor_rpc():
    transport = SupervisorTransport(None, None, 'unix:///tmp/supervisor.sock')
    return xmlrpc.client.ServerProxy('http://localhost', transport=transport)

def start_service(name):
    rpc = get_supervisor_rpc()
    rpc.supervisor.startProcess(name)

def stop_service(name):
    rpc = get_supervisor_rpc()
    rpc.supervisor.stopProcess(name)

def all_services():
    rpc = get_supervisor_rpc()
    return rpc.supervisor.getAllProcessInfo()

def get_service_log(name, offset=0, length=10000):
    rpc = get_supervisor_rpc()
    return rpc.supervisor.readProcessStdoutLog(name, offset, length)

def wait_for_supervisor():
    import time
    while True:
        if Path('/tmp/supervisor.sock').exists():
            break
        else:
            time.sleep(0.1)
@dataclass
class MercureService:
    name: str
    command: str
    numprocs: int = 1
    stopasgroup: bool = False
    startsecs: int = 0

def create_temp_dirs():
    temp_route = Path(tempfile.mkdtemp(prefix='mercure_', dir='/tmp'))
    for d in ['config','data']:
        temp_route.joinpath(d).mkdir()
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing"]:
        temp_route.joinpath('data', k).mkdir()
    return temp_route


def write_mercure_config(mercure_base, config = {}):
    mercure_config = { k: v for k, v in mercure_defaults.items()}
    for folder in (mercure_base / 'data').iterdir():
        mercure_config[f"{folder.name}_folder"] = str(folder)

    mercure_config["series_complete_trigger"] = 1
    mercure_config["study_complete_trigger"] = 2
    mercure_config["bookkeeper_api_key"] = "test"
    mercure_config["port"] = 21113
    mercure_config["bookkeeper"] = "0.0.0.0:8080"
    mercure_config.update(config)
    with (mercure_base / 'config' / 'mercure.json').open('w') as fp:
        json.dump(mercure_config, fp)

    bookkeeper_config = f"""
PORT=8080
HOST=0.0.0.0
DATABASE_URL=sqlite:///{mercure_base}/data/bookkeeper.sqlite3
DEBUG=True
"""
    with (mercure_base / 'config' / 'bookkeeper.env').open('w') as fp:
        fp.write(bookkeeper_config)

def start_mercure(config = {}, services_to_start=["bookkeeper", "reciever", "router", "processor", "dispatcher"], mercure_base= None):
    global supervisor_process
    if mercure_base is None:
        mercure_base = create_temp_dirs()
    write_mercure_config(mercure_base, config)

    services = [
        MercureService("bookkeeper", f"/opt/mercure/env/bin/python {here}/bookkeeper.py"), 
        MercureService("router", f"/opt/mercure/env/bin/python {here}/router.py", numprocs=5), 
        MercureService("processor", f"/opt/mercure/env/bin/python {here}/processor.py", numprocs=2), 
        MercureService("dispatcher", f"/opt/mercure/env/bin/python {here}/dispatcher.py", numprocs=5)
    ]
    # services[0].startsecs = 5
    services += [MercureService(f"receiver", f"{here}/receiver.sh", stopasgroup=True)]
    supervisor_process = start_supervisor(services,mercure_base)
    # Wait for Supervisor to fully start
    
    for service in services_to_start:
        start_service(service)
    return services, mercure_base

def is_dicoms_received(mercure_base, dicoms):
    dicoms_recieved = set()
    for series_folder in (mercure_base / 'data' / 'incoming').glob('*/'):
        for dicom in series_folder.glob('*.dcm'):
            ds_ = pydicom.dcmread(dicom)
            assert ds_.SeriesInstanceUID == series_folder.name
            assert ds_.SOPInstanceUID not in dicoms_recieved
            dicoms_recieved.add(ds_.SOPInstanceUID) 
            
    assert dicoms_recieved == set(ds.SOPInstanceUID for ds in dicoms)
    print(f"Received {len(dicoms)} dicoms as expected")

def is_dicoms_in_folder(folder, dicoms):
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

def stop_mercure(supervisor_process):
    logs = {}
    for service in all_services():
        if service['state'] in RUNNING_STATES:
            try:
                stop_service(service['name'])
            except xmlrpc.client.Fault as e:
                if e.faultCode == 10:
                    stop_service(service['group']+":*")
        # log = get_service_log(service['name'])
        # if log:
        log =  Path(service['stdout_logfile']).read_text()
        if log:
            logs[service['name']] = log
    try:
        supervisor_process.terminate()
        supervisor_process.join()
    except asyncore.ExitNow:
        pass
    return logs


def mytest(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """A wrapper function"""
 
        # Extend some capabilities of func
        try:
            func(*args, **kwargs)
        except:
            logs = stop_mercure(supervisor_process)
            for l in logs:
                print(f"====== {l} ======")
                print(logs[l])
            print("=============")
            raise
        else:
            print(func.__name__, 'succeeded')
            logs = stop_mercure(supervisor_process)
            if os.environ.get('LOGS'):
                for l in logs:
                    print(f"====== {l} ======")
                    print(logs[l])
                print("=============")
    return wrapper

@mytest
def case_simple(n_series=1):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="notification", action_trigger="series"
            ).dict(),
        }
    }
    services, mercure_base = start_mercure(config, ["receiver"])
    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Greg'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    time.sleep(2)
    is_dicoms_received(mercure_base, ds)
    start_service("router:*")
    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "data" / "success", ds)

@mytest
def case_dispatch(n_series=1):
    mercure_base = create_temp_dirs()
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
    start_mercure(config, ["receiver", "router:*"], mercure_base)
    (mercure_base / "target").mkdir(parents=True, exist_ok=True)

    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "data" / "outgoing", ds)
    
    start_service("dispatcher:*")
    time.sleep(2+n_series/2)
    is_dicoms_in_folder(mercure_base / "target", ds)

    
@mytest
def case_process(n_series=1):
    mercure_base = create_temp_dirs()
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
    start_mercure(config, ["receiver", "router:*", "dispatcher:*", "processor:*"], mercure_base)

    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    for _ in range(120):
        try:
            is_dicoms_in_folder(mercure_base / "target", ds)
            break
        except AssertionError as e:
            time.sleep(1)
    else:
        raise Exception("Failed to find dicoms in target folder after 120 seconds.")


def test_case_simple():
    case_simple(5)

def test_case_dispatch():
    case_dispatch(5)

def test_case_process():
    case_process(5)

if __name__ == '__main__':
    services = None
    # test_case_simple(20)
    # test_case_dispatch(20)
    case_process(10)
        # # When done, stop supervisor
        # print("\nService Logs:")
        # for service in services:
        #     print(f"\n--- {service.name} Log ---")
        #     log = get_service_log(service.name)
        #     print(log)
        # print("Supervisor stopped")