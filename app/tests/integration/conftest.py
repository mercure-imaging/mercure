import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import time
import xmlrpc.client
from pathlib import Path
from typing import Any, Callable, Generator, Optional

import pytest
from common.config import mercure_defaults
from supervisor.options import ServerOptions
from supervisor.states import RUNNING_STATES
from supervisor.supervisord import Supervisor
from supervisor.xmlrpc import SupervisorTransport

from app.tests.integration.common import MercureService


# current workding directory
def here() -> str:
    if os.path.exists(os.path.abspath(os.getcwd()) + "/app"):
        return os.path.abspath(os.getcwd())
    else:
        return os.path.abspath(os.path.dirname(os.getcwd()))


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
                # environment=""
                # if service.environment:
                #     environment = ","
                #     for key, value in service.environment.items():
                #         environment += f"{key}=\"{value}\","
                #     if environment[-1] == ',':
                #         environment = environment[:-1]
                f.write(f"""
[program:{service.name}]
command={service.command}
process_name=%(program_name)s{'_%(process_num)d' if service.numprocs>1 else ''}
directory={os.getcwd()}
autostart=false
autorestart=false
redirect_stderr=true
startsecs={service.startsecs}
stopasgroup={str(service.stopasgroup).lower()}
numprocs={service.numprocs}
environment=MERCURE_CONFIG_FOLDER="{self.mercure_base}/config", MERCURE_BASEPATH="{self.mercure_base}"
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
        self.transport = SupervisorTransport(None, None, f'unix://{self.socket}')
        self.rpc = xmlrpc.client.ServerProxy('http://localhost', transport=self.transport)

    def start_service(self, name) -> None:
        self.rpc.supervisor.startProcess(name)

    def stop_service(self, name) -> None:
        self.rpc.supervisor.stopProcess(name)

    def all_services(self) -> Any:
        return self.rpc.supervisor.getAllProcessInfo()  # type: ignore

    def get_service_log(self, name, offset=0, length=10000) -> Any:
        return self.rpc.supervisor.readProcessStdoutLog(name, offset, length)  # type: ignore

    def stream_service_logs(self, name, timeout=1) -> None:
        offset = 0
        while True:
            log_data, offset, overflow = self.rpc.supervisor.tailProcessStdoutLog(name, offset, 1024)  # type: ignore
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
            self.transport.close()
            self.process.terminate()
            self.process.join()
        except Exception as e:
            print(e)
            pass


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
                    supervisor.stop_service(service['group'] + ":*")
        # log = get_service_log(service['name'])
        # if log:
        log = Path(service['stdout_logfile']).read_text()
        if log:
            logs[service['name']] = log
    return logs


@pytest.fixture(scope="session")
def python_bin():
    if os.environ.get("CLEAN_VENV"):
        with tempfile.TemporaryDirectory(prefix="mercure_venv") as venvdir:
            subprocess.run([sys.executable, "-m", "venv", venvdir], check=True)
            subprocess.run([os.path.join(venvdir, "bin", "pip"), "install", "-r", f"{here()}/requirements.txt"], check=True)
            yield (venvdir + "/bin/python")
    else:
        yield sys.executable


@pytest.fixture(scope="function")
def mercure_base() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory(prefix='mercure_') as temp_dir:
        temp_path = Path(temp_dir)
        for d in ['config', 'data']:
            (temp_path / d).mkdir()
        for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing", "jobs"]:
            (temp_path / 'data' / k).mkdir()
        yield temp_path


@pytest.fixture(scope="function")
def mercure(supervisord: Callable[[Any], SupervisorManager], python_bin
            ) -> Generator[Callable[[Any], SupervisorManager], None, None]:
    def py_service(service, **kwargs) -> MercureService:
        if 'command' not in kwargs:
            kwargs['command'] = f"{python_bin} {here()}/app/{service}.py"
        return MercureService(service, **kwargs)
    services = [
        py_service("bookkeeper", startsecs=6),
        py_service("router", numprocs=5),
        py_service("processor", numprocs=2),
        py_service("dispatcher", numprocs=5),
        py_service("worker_fast", command=f"{python_bin} -m rq.cli worker mercure_fast"),
        py_service("worker_slow", command=f"{python_bin} -m rq.cli worker mercure_slow")
    ]
    services += [MercureService("receiver", f"{here()}/app/receiver.sh --inject-errors", stopasgroup=True)]
    supervisor = supervisord(services)

    def do_start(services_to_start=["bookkeeper", "reciever", "router", "processor", "dispatcher"]) -> SupervisorManager:
        for service in services_to_start:
            supervisor.start_service(service)
        return supervisor
    yield do_start
    logs = stop_mercure(supervisor)
    for log_title in logs:
        print(f"====== {log_title} ======")
        print(logs[log_title])
    print("=============")


@pytest.fixture(scope="function")
def mercure_config(mercure_base, receiver_port, bookkeeper_port):
    mercure_config = {k: v for k, v in mercure_defaults.items()}
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
