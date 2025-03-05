
import os
import socket
import uuid
from typing import Any, Callable, Dict

import common  # noqa: F401
import common.config as config
import process  # noqa: F401
import pytest
import routing  # noqa: F401
from bookkeeping import bookkeeper
from common.types import Config


def spy_on(mocker, obj) -> None:
    pieces = obj.split(".")
    module = ".".join(pieces[0:-1])
    mocker.patch(obj, new=mocker.spy(eval(module), pieces[-1]))


def spies(mocker, list_of_spies) -> None:
    for spy in list_of_spies:
        spy_on(mocker, spy)


def attach_spies(mocker) -> None:
    spies(
        mocker,
        [
            "routing.route_series.push_series_serieslevel",
            "routing.route_series.push_serieslevel_outgoing",
            "routing.route_studies.route_study",
            "routing.generate_taskfile.create_series_task",
            "routing.route_studies.move_study_folder",
            "routing.route_studies.push_studylevel_error",
            "routing.generate_taskfile.create_study_task",
            "routing.router.route_series",
            "routing.router.route_studies",
            "process.processor.process_series",
            # "process.process_series",
            "common.monitor.post",
            "common.monitor.send_event",
            "common.monitor.send_register_series",
            "common.monitor.send_register_task",
            "common.monitor.send_task_event",
            "common.monitor.async_send_task_event",
            "common.monitor.send_processor_output",
            "common.monitor.send_update_task",
            "common.notification.trigger_notification_for_rule",
            "common.notification.send_email",
            "uuid.uuid1"
        ],
    )


@pytest.fixture(scope="function")
def mocked(mocker):
    mocker.resetall()
    attach_spies(mocker)
    return mocker


@pytest.fixture(scope="module")
def bookkeeper_port():
    return random_port()


@pytest.fixture(scope="module")
def receiver_port():
    return random_port()


@pytest.fixture(scope="function", autouse=True)
def mercure_config(fs, bookkeeper_port) -> Callable[[Dict], Config]:
    # TODO: config from previous calls seems to leak in here
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/data/test_config.json")

    fs.add_real_file(config_path, target_path=config.configuration_filename, read_only=False)
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing", "jobs"]:
        fs.create_dir(f"/var/{k}")

    def set_config(extra: Dict[Any, Any] = {}) -> Config:
        config.read_config()
        config.mercure = Config(**{**config.mercure.dict(), **extra})  # type: ignore
        print(config.mercure.targets)
        config.save_config()
        return config.mercure

    # set_config()
    # sqlite3 is not inside the fakefs so this is going to be a real file
    set_config({"bookkeeper": "sqlite:///tmp/mercure_bookkeeper_" + str(uuid.uuid4()) + ".db"})

    bookkeeper_env = f"""PORT={bookkeeper_port}
HOST=0.0.0.0
DATABASE_URL={config.mercure.bookkeeper}"""
    fs.create_file(bookkeeper.bk_config.config_filename, contents=bookkeeper_env)

    fs.add_real_directory(os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/..'))
    # fs.add_real_file(os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/..'), read_only=True)
    return set_config


def random_port() -> int:
    """
    Generate a free port number to use as an ephemeral endpoint.
    """
    s = socket.socket()
    s.bind(('', 0))  # bind to any available port
    port = s.getsockname()[1]  # get the port number
    s.close()
    return int(port)
