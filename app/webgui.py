"""
webgui.py
=========
The web-based graphical user interface of mercure.
"""

import asyncio
import base64
# Standard python includes
import contextlib
import datetime
import html
import json
import os
import random
import shutil
import string
import subprocess
import sys
import traceback
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# App-specific includes
import common.config as config
import common.helper as helper
import common.monitor as monitor
import dateutil
import distro
import hupper
import uvicorn
import webinterface.api as api
import webinterface.dashboards as dashboards
import webinterface.modules as modules
import webinterface.queue as queue
import webinterface.rules as rules
import webinterface.services as services
import webinterface.targets as targets
import webinterface.users as users
from common.constants import mercure_defs, mercure_names
from common.generate_test_series import generate_series, generate_several_protocols
from common.types import DicomTarget, Module, Rule
from decoRouter import Router as decoRouter
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser, requires
from starlette.config import Config
from starlette.datastructures import Secret
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route, Router
from starlette.staticfiles import StaticFiles
from webinterface.common import async_run, get_csp_nonce, redis, rq_fast_scheduler, templates
from webinterface.dashboards.query.jobs import QueryPipeline

import docker
import nomad

router = decoRouter()


###################################################################################
# Helper classes
###################################################################################


logger = config.get_logger()


try:
    nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)  # type: ignore
    # TODO: Print message only if connection to Nomad successful
    logger.info("Connected to Nomad")
except Exception:
    nomad_connection = None


class ExtendedUser(SimpleUser):
    def __init__(self, username: str, is_admin: bool = False) -> None:
        self.username = username
        self.admin_status = is_admin

    @property
    def is_admin(self) -> bool:
        return self.admin_status


class SessionAuthBackend(AuthenticationBackend):
    async def authenticate(self, request):

        username = request.session.get("user")
        if username is None:
            return

        credentials = ["authenticated"]
        is_admin = False

        if request.session.get("is_admin", "False") == "Jawohl":
            credentials.append("admin")
            is_admin = True

        return AuthCredentials(credentials), ExtendedUser(username, is_admin)


webgui_config = None
SECRET_KEY: Secret
WEBGUI_PORT: int
WEBGUI_HOST: str
DEBUG_MODE: bool


def read_webgui_config() -> Config:
    global webgui_config, SECRET_KEY, WEBGUI_HOST, WEBGUI_PORT, DEBUG_MODE
    webgui_config = Config((os.getenv("MERCURE_CONFIG_FOLDER") or "/opt/mercure/config") + "/webgui.env")

    # Note: PutSomethingRandomHere is the default value in the shipped configuration file.
    #       The app will not start with this value, forcing the users to set their onw secret
    #       key. Therefore, the value is used as default here as well.
    SECRET_KEY = webgui_config("SECRET_KEY", cast=Secret, default=Secret("PutSomethingRandomHere"))
    WEBGUI_PORT = webgui_config("PORT", cast=int, default=8000)
    WEBGUI_HOST = webgui_config("HOST", default="0.0.0.0")
    DEBUG_MODE = webgui_config("DEBUG", cast=bool, default=True)
    return webgui_config


@contextlib.asynccontextmanager
async def lifespan(app):
    result = startup(app)
    yield result
    await shutdown()


def startup(app: Starlette):
    state = {"redis_connected": False}
    try:
        response = redis.ping()
        if response:
            logger.info("Redis connection validated.")
            state["redis_connected"] = True
        else:
            raise Exception("Redis connection failed")
    except Exception:
        logger.error("Could not connect to Redis", exc_info=True)

    if state["redis_connected"]:
        scheduled_jobs = rq_fast_scheduler.get_jobs()
        for job in scheduled_jobs:
            if job.meta.get("type") != "offpeak":
                continue
            rq_fast_scheduler.cancel(job)
        rq_fast_scheduler.schedule(
            scheduled_time=datetime.datetime.utcnow(),
            func=QueryPipeline.update_all_offpeak,
            interval=60,
            meta={"type": "offpeak"},
            repeat=None
        )
    monitor.configure("webgui", "main", config.mercure.bookkeeper)
    monitor.send_event(monitor.m_events.BOOT, monitor.severity.INFO, f"PID = {os.getpid()}")
    return state


async def shutdown() -> None:
    monitor.send_event(monitor.m_events.SHUTDOWN, monitor.severity.INFO, "")
    await delete_old_tests()


async def delete_old_tests() -> Response:
    tests = await monitor.get_tests()
    old_tests = [
        t["id"]
        for t in tests
        # if t["time_end"] is None
        if datetime.datetime.strptime(t["time_begin"], "%Y-%m-%d %H:%M:%S")
        < datetime.datetime.now() - datetime.timedelta(hours=1)
    ]
    config.read_config()
    for i in old_tests:
        if (t := f"{i}_self_test_target") in config.mercure.targets:
            del config.mercure.targets[t]
        if (t := f"{i}_self_test_module") in config.mercure.modules:
            del config.mercure.modules[t]
        if (t := f"{i}_self_test_rule_begin") in config.mercure.rules:
            del config.mercure.rules[t]
        if (t := f"{i}_self_test_rule_end") in config.mercure.rules:
            del config.mercure.rules[t]

    config.save_config()

    return PlainTextResponse("OK")


###################################################################################
# Logs endpoints
###################################################################################


@router.get("/logs")
@requires(["authenticated", "admin"], redirect="login")
async def show_first_log(request) -> Response:
    """Get the first service entry and forward to corresponding log entry point."""
    if services.services_list:
        first_service = next(iter(services.services_list))
        return RedirectResponse(url="/logs/" + first_service, status_code=303)
    else:
        return PlainTextResponse("No services configured")


def get_nomad_logs(service, log_size: int) -> bytes:
    """Reads the service log when running a nomad-type installation."""
    allocations = nomad_connection.job.get_allocations("mercure")
    alloc_id = next((a["ID"] for a in allocations if a["ClientStatus"] == "running"))

    def nomad_log_type(type="stderr") -> Any:
        return nomad_connection.client.stream_logs.stream(alloc_id, service, type, origin="end", offset=log_size)

    log_response = nomad_log_type() or nomad_log_type("stdout")
    return base64.b64decode(json.loads(log_response).get("Data", ""))


@router.get("/logs/{service}")
@requires(["authenticated", "admin"], redirect="login")
async def show_log(request) -> Response:
    """Render the log for the given service. The time range can be specified via URL parameters."""
    requested_service = request.path_params["service"]

    # Get optional start and end dates from the URL. Make sure that the date format is clean.
    start_dt: Optional[datetime.datetime] = None
    end_dt: Optional[datetime.datetime] = None
    start_date = ""
    start_time = "00:00"
    end_date = ""
    end_time = "00:00"

    try:
        start_date = request.query_params.get("from", "")
        start_time = request.query_params.get("from_time", "00:00")
        start_timestamp = f"{start_date} {start_time}"
        start_dt = datetime.datetime.strptime(start_timestamp, "%Y-%m-%d %H:%M")
    except ValueError:
        start_dt = None
        start_timestamp = ""

    try:
        end_date = request.query_params.get("to", "")
        # Make sure end time includes the day-of, unless otherwise specified
        end_time = request.query_params.get("to_time", "23:59")
        end_timestamp = f"{end_date} {end_time}"
        end_dt = datetime.datetime.strptime(end_timestamp, "%Y-%m-%d %H:%M")
    except ValueError:
        end_timestamp = ""

    service_logs = {}
    for service in services.services_list:
        service_logs[service] = {
            "id": service,
            "name": services.services_list[service]["name"],
            "systemd": services.services_list[service].get("systemd_service", ""),
            "docker": services.services_list[service].get("docker_service", ""),
        }

    if requested_service not in service_logs:
        return PlainTextResponse("Service does not exist.")

    if (
        "systemd_service" not in services.services_list[requested_service]
        and "docker_service" not in services.services_list[requested_service]
    ):
        return PlainTextResponse("Service incorrectly configured.")

    return_code = -1
    raw_logs = bytes()

    # Get information about the type of mercure installation on the server
    runtime = helper.get_runner()

    # Fetch the log files depending on how mercure has been installed
    if runtime == "nomad" and nomad_connection is not None:
        try:
            raw_logs = get_nomad_logs(requested_service, 50000)
            return_code = 0
        except Exception:
            pass
        sub_services = []
    elif runtime == "systemd":
        start_date_cmd = ""
        end_date_cmd = ""
        if start_timestamp:
            start_date_cmd = f'--since "{start_timestamp} {config.mercure.local_time}"'
        if end_timestamp:
            end_date_cmd = f'--until "{end_timestamp} {config.mercure.local_time}"'

        service_name_or_list = services.services_list[requested_service]["systemd_service"]
        if isinstance(service_name_or_list, list):
            service_name = request.query_params.get("subservice", "missing")
            # Redirect to the first sub-service if none has been specified in the URL
            if service_name == "missing":
                return RedirectResponse(url="/logs/" + requested_service + "?subservice=" + service_name_or_list[0],
                                        status_code=303)
            sub_services = service_name_or_list
        else:
            service_name = service_name_or_list
            sub_services = []

        run_result = await async_run(
            f"sudo journalctl -n 1000 -u "
            f'{service_name} '
            f"{start_date_cmd} {end_date_cmd} "
            "-o short-iso --no-hostname"
        )
        return_code = -1 if run_result[0] is None else run_result[0]
        raw_logs = run_result[1]

    elif runtime == "docker":
        client = docker.from_env()  # type: ignore
        try:
            service_name_or_list = services.services_list[requested_service]["docker_service"]
            if isinstance(service_name_or_list, list):
                service_name = request.query_params.get("subservice", "missing")
                # Redirect to the first sub-service if none has been specified in the URL
                if service_name == "missing":
                    return RedirectResponse(url="/logs/" + requested_service + "?subservice=" + service_name_or_list[0],
                                            status_code=303)
                sub_services = service_name_or_list
            else:
                service_name = service_name_or_list
                sub_services = []

            container = client.containers.get(service_name)
            container.reload()
            try:
                local_tz: datetime.tzinfo = dateutil.tz.gettz(config.mercure.local_time)  # type: ignore
                if start_dt:
                    start_dt = start_dt.replace(tzinfo=local_tz)
                if end_dt:
                    end_dt = end_dt.replace(tzinfo=local_tz)
            except Exception:
                pass
            raw_logs = container.logs(since=start_dt, until=end_dt, timestamps=True, tail=1000)
            return_code = 0
        except (docker.errors.NotFound, docker.errors.APIError) as e:  # type: ignore
            logger.error(e)
            return_code = 1

    # return_code, raw_logs = (await async_run("/usr/bin/nomad alloc logs -job -stderr -f -tail mercure router"))[:2]
    if return_code == 0:
        log_content = html.escape(str(raw_logs.decode()))
        log_content = helper.localize_log_timestamps(log_content, config)

    else:
        log_content = "Error reading log information"
        if start_date or end_date:
            log_content = log_content + "<br /><br />Are the From/To settings valid?"

    if request.headers["accept"] == 'application/json':
        if return_code == 0:
            return JSONResponse({"logs": str(raw_logs.decode())})
    template = "logs.html"
    context = {
        "request": request,

        "page": "logs",
        "service_logs": service_logs,
        "log_id": requested_service,
        "log_content": log_content,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "end_time_available": runtime in ("docker", "systemd"),
        "start_time_available": runtime in ("docker", "systemd"),
        "sub_services": sub_services,
        "subservice": request.query_params.get("subservice", None)
    }
    return templates.TemplateResponse(template, context)


###################################################################################
# Configuration endpoints
###################################################################################


@router.get("/configuration")
@requires(["authenticated"], redirect="homepage")
async def configuration(request) -> Response:
    """Shows the current configuration of the mercure appliance."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Error reading configuration file.")
    template = "configuration.html"
    config_edited = int(request.query_params.get("edited", 0))
    os_string = distro.name(True)
    runtime = helper.get_runner()
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "homepage",
        "config": config.mercure,
        "os_string": os_string,
        "config_edited": config_edited,
        "runtime": runtime,
    }
    return templates.TemplateResponse(template, context)


@router.get("/configuration/edit")
@requires(["authenticated", "admin"], redirect="homepage")
async def configuration_edit(request) -> Response:
    """Shows a configuration editor"""

    # Check for existence of lock file
    cfg_file = Path(config.configuration_filename)
    cfg_lock = Path(cfg_file.parent / cfg_file.stem).with_suffix(mercure_names.LOCK)
    if cfg_lock.exists():
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    try:
        with open(cfg_file, "r") as json_file:
            config_content = json.load(json_file)
    except Exception:
        return PlainTextResponse("Error reading configuration file.")

    config_content = json.dumps(config_content, indent=4, sort_keys=False)

    template = "configuration_edit.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "homepage",
        "config_content": config_content,
    }
    return templates.TemplateResponse(template, context)


@router.post("/configuration/edit")
@requires(["authenticated", "admin"], redirect="homepage")
async def configuration_edit_post(request) -> Response:
    """Updates the configuration after post from editor"""

    form = dict(await request.form())
    editor_json = form.get("editor", "{}")
    try:
        validated_json = json.loads(editor_json)
    except ValueError:
        return PlainTextResponse("Invalid JSON data transferred.")

    try:
        config.write_configfile(validated_json)
        config.read_config()
    except ValueError:
        return PlainTextResponse("Unable to write config file. Might be locked.")

    logger.info("Updates mercure configuration file.")
    monitor.send_webgui_event(monitor.w_events.CONFIG_EDIT, request.user.display_name, "")

    return RedirectResponse(url="/configuration?edited=1", status_code=303)


###################################################################################
# Login/logout endpoints
###################################################################################


@router.get("/login")
async def login(request) -> Response:
    """Shows the login page."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Error reading configuration file.")
    request.session.clear()
    template = "login.html"
    context = {
        "request": request,

        "appliance_name": config.mercure.get("appliance_name", "master"),
    }
    return templates.TemplateResponse(template, context)


# @router.get("/old_tests", methods=["GET"])


async def self_test_cleanup(test_id: str, delay: int = 60) -> None:
    """Delete the rules and targets for this test after a delay"""
    await asyncio.sleep(delay)
    config.read_config()

    if f"{test_id}_self_test_target" in config.mercure.targets:
        del config.mercure.targets[f"{test_id}_self_test_target"]
    if f"{test_id}_self_test_module" in config.mercure.modules:
        del config.mercure.modules[f"{test_id}_self_test_module"]

    for p in ("begin", "end"):
        if f"{test_id}_self_test_rule_{p}" in config.mercure.rules:
            del config.mercure.rules[f"{test_id}_self_test_rule_{p}"]
    config.save_config()


@router.post("/self_test_notification")
async def self_test_notification(request) -> Response:
    json = await request.json()
    test_id = json.get("test_id", "")

    if json["rule"].endswith("self_test_rule_begin"):
        if json["event"] == "RECEIVED":
            await monitor.do_post("test-begin", dict(json=dict(id=test_id, task_id=json["task_id"])))

    elif json["rule"].endswith("self_test_rule_end"):
        if json["event"] == "COMPLETED":
            await monitor.do_post("test-end", dict(json=dict(id=test_id, status="success")))
            for p in ("begin", "end"):
                if f"{test_id}_self_test_rule_{p}" in config.mercure.rules:
                    config.mercure.rules[f"{test_id}_self_test_rule_{p}"].disabled = True
            try:
                config.save_config()
            except ResourceWarning:
                pass

            asyncio.ensure_future(self_test_cleanup(test_id), loop=monitor.loop)

    return PlainTextResponse("OK")


@router.post("/self_test")
@requires(["authenticated", "admin"], redirect="homepage")
async def self_test(request) -> Response:
    """generate a test rule"""
    form_data = await request.form()

    runner = helper.get_runner()
    receiver_port = "11112"
    gui_port = "8000"
    test_type = form_data.get("type", "route")
    rule_type = form_data.get("rule_type", "series")

    if runner == "docker":
        receiver_host = "receiver"
        gui_host = "ui"
    elif runner == "nomad":
        receiver_host = "localhost"
        gui_host = "localhost"
    elif runner == "systemd":
        receiver_host = "localhost"
        gui_host = "localhost"
    else:
        receiver_host = "localhost"
        gui_host = "localhost"

    if form_data.get("receiver_port", "") != "":
        receiver_port = form_data["receiver_port"]
    if form_data.get("gui_port", "") != "":
        gui_port = form_data["gui_port"]
    if form_data.get("receiver_host", "") != "":
        receiver_host = form_data["receiver_host"]
    if form_data.get("gui_host", "") != "":
        gui_host = form_data["gui_host"]

    try:
        test_id = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        test_rule = f"{test_id}_self_test_rule"
        test_target = f"{test_id}_self_test_target"
        config.mercure.targets[test_target] = DicomTarget(
            ip=receiver_host, port=receiver_port, aet_source="mercure", aet_target=f"{test_id}_end"
        )

        config.read_config()
        # "begin" rule is used to trigger the test. It routes to a test_target, which is the mercure receiver.
        config.mercure.rules[test_rule + "_begin"] = Rule(
            rule=f'@ReceiverAET@ == "{test_id}_begin"',
            target=test_target,
            action="route",
            notification_trigger_completion=False,
            action_trigger=rule_type,
            notification_webhook=f"http://{gui_host}:{gui_port}/self_test_notification",
            notification_payload=f'"rule":"@rule@", "event":"@event@", "test_id":"{test_id}", "task_id":"@task_id@"',
        )
        if test_type == "process":
            config.mercure.modules[test_rule + "_self_test_module"] = Module(
                docker_tag="mercureimaging/mercure-dummy-processor:latest",
            )
            config.mercure.modules[test_rule + "_self_test_module_2"] = Module(
                docker_tag="mercureimaging/mercure-dummy-processor:latest",
            )
            config.mercure.rules[test_rule + "_begin"].action = "both"
            config.mercure.rules[test_rule + "_begin"].processing_module = [test_rule + "_self_test_module",
                                                                            test_rule + "_self_test_module_2"]

        # "end" rule is triggered when the test is completed. It just performs a notification to register the test success.
        config.mercure.rules[test_rule + "_end"] = Rule(
            rule=f'@ReceiverAET@ == "{test_id}_end"',
            action="notification",
            action_trigger=rule_type,
            notification_webhook=f"http://{gui_host}:{gui_port}/self_test_notification",
            notification_trigger_reception=False,
            notification_payload=f'"rule":"@rule@", "event":"@event@", "test_id":"{test_id}"',
        )

        config.save_config()

        asyncio.ensure_future(self_test_cleanup(test_id, 60 * 60), loop=monitor.loop)
        logger.info("Posting test-begin...")
        tmpdir = Path("/tmp/mercure/self_test_" + test_id)
        Path("/tmp/mercure").mkdir(exist_ok=True)
        if rule_type == "study":
            generate_several_protocols(tmpdir, ["PROT1", "PROT2"])
        else:
            generate_series(tmpdir, 10, series_description="self_test_series " + test_id)

    except Exception:
        return PlainTextResponse(f"Error initializing test: {traceback.format_exc()}", status_code=500)

    # shutil.copytree("./test_series", tmpdir)
    command = (f"""dcmsend {receiver_host} {receiver_port} +r +sd {tmpdir} """
               f"""-aet "mercure" -aec "{test_id}_begin" -nuc +sp '*.dcm' -to 60""")
    try:
        subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error sending dicoms: {command}")
        return PlainTextResponse("Could not submit dicoms for test:\n" + e.output.decode("utf-8"))

    await monitor.do_post("test-begin", dict(json=dict(id=test_id, type=test_type, rule_type=rule_type)))
    # logger.info(f"self_test: {output.decode('utf-8')}")
    return JSONResponse({"success": "true", "test_id": test_id})


@router.post("/login")
async def login_post(request) -> Response:
    """Evaluate the submitted login information. Redirects to index page if login information valid, otherwise back to login.
    On the first login, the user will be directed to the settings page and asked to change the password."""
    try:
        users.read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    if users.evaluate_password(form.get("username", ""), form.get("password", "")):
        request.session.update({"user": form["username"]})

        if users.is_admin(form["username"]) is True:
            request.session.update({"is_admin": "Jawohl"})

        monitor.send_webgui_event(
            monitor.w_events.LOGIN,
            form["username"],
            "{admin}".format(admin="ADMIN" if users.is_admin(form["username"]) else ""),
        )

        if users.needs_change_password(form["username"]):
            return RedirectResponse(url="/settings", status_code=303)
        else:
            return RedirectResponse(url="/", status_code=303)
    else:
        if request.client.host is None:
            source_ip = "UNKOWN IP"
        else:
            source_ip = request.client.host
        monitor.send_webgui_event(monitor.w_events.LOGIN_FAIL, form["username"], source_ip)

        template = "login.html"
        context = {
            "request": request,
            "invalid_password": 1,

            "appliance_name": config.mercure.get("appliance_name", "mercure Router"),
        }
        return templates.TemplateResponse(template, context)


@router.get("/logout")
async def logout(request):
    """Logouts the users by clearing the session cookie."""
    monitor.send_webgui_event(monitor.w_events.LOGOUT, request.user.display_name, "")
    request.session.clear()
    return RedirectResponse(url="/login")


@router.get("/settings")
@requires(["authenticated"], redirect="login")
async def settings_edit(request) -> Response:
    """Shows the settings for the current user.
       Renders the same template as the normal user edit, but with parameter own_settings=True."""
    try:
        users.read_users()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    own_name = request.user.display_name

    template = "users_edit.html"
    context = {
        "request": request,

        "page": "settings",
        "edituser": own_name,
        "edituser_info": users.users_list[own_name],
        "own_settings": "True",
        "change_password": users.users_list[own_name].get("change_password", "False"),
    }
    return templates.TemplateResponse(template, context)


###################################################################################
# Homepage endpoints
###################################################################################

async def get_service_status(runtime) -> List[Dict[str, Any]]:
    service_status = {service: {
        "id": service,
        "name": value["name"],
        "running": None
    } for service, value in services.services_list.items()}
    logger.warning(service_status)
    logger.warning(services.services_list)
    try:
        for service_id, service_info in services.services_list.items():
            running_status: Optional[bool] = False

            if runtime == "systemd":
                systemd_services = service_info["systemd_service"]
                if not isinstance(systemd_services, list):
                    systemd_services = [systemd_services]

                for service_name in systemd_services:
                    exit_code, _, _ = await async_run(f"systemctl is-active {service_name}")
                    if exit_code == 0:
                        running_status = True
                    else:
                        running_status = False
                        break

            elif runtime == "docker":
                client = docker.from_env()  # type: ignore
                docker_services = service_info["docker_service"]
                if not isinstance(docker_services, list):
                    docker_services = [docker_services]

                try:
                    for docker_service in docker_services:
                        container = client.containers.get(docker_service)
                        container.reload()
                        status = container.status
                        """restarting, running, paused, exited"""
                        if status == "running":
                            running_status = True

                except (docker.errors.NotFound, docker.errors.APIError):  # type: ignore
                    running_status = False
            elif runtime == "nomad":
                if nomad_connection is None:
                    running_status = None
                else:
                    allocations = nomad_connection.job.get_allocations("mercure")
                    running_alloc = [a for a in allocations if a["ClientStatus"] == "running"]
                    if not running_alloc:
                        running_status = False
                    else:
                        alloc = running_alloc[0]
                        if not alloc["TaskStates"].get(service_id):
                            running_status = False
                        else:  # TODO: fix this for workers?
                            running_status = alloc["TaskStates"][service_id]["State"] == "running"

            service_status[service_id]["running"] = running_status
    except Exception:
        logger.exception("Failed to get service status.")
    finally:
        return list(service_status.values())


@router.get("/")
@requires("authenticated", redirect="login")
async def homepage(request) -> Response:
    """Renders the index page that shows information about the system status."""
    used_space: float = 0
    free_space: Union[int, str] = 0
    total_space: Union[int, str] = 0
    disk_total: Union[int, str] = 0
    runtime = helper.get_runner()

    try:
        disk_total, disk_used, disk_free = shutil.disk_usage(config.mercure.incoming_folder)

        if disk_total == 0:
            disk_total = 1

        used_space = 100 * disk_used / disk_total
        free_space = disk_free // (2**30)
        total_space = disk_total // (2**30)
    except Exception:
        used_space = -1
        free_space = "N/A"
        disk_total = "N/A"

    try:
        service_status = await get_service_status(runtime)
    except Exception as e:
        logger.error(f"Error getting service status: {e}")
        service_status = [{}]

    template = "index.html"
    context = {
        "request": request,

        "page": "homepage",
        "used_space": used_space,
        "free_space": free_space,
        "total_space": total_space,
        "service_status": service_status,
        "runtime": runtime,
    }
    return templates.TemplateResponse(template, context)


@router.post("/services/control")
@requires(["authenticated", "admin"], redirect="homepage")
async def control_services(request) -> Response:
    form = dict(await request.form())
    action = ""
    runtime = helper.get_runner()

    if form.get("action", "") == "start":
        action = "start"
    if form.get("action", "") == "stop":
        action = "stop"
    if form.get("action", "") == "restart":
        action = "restart"
    if form.get("action", "") == "kill":
        action = "kill"

    controlservices = form.get("services", "").split(",")

    if action and len(controlservices) > 0:
        for service in controlservices:
            if not str(service) in services.services_list:
                continue

            if runtime == "systemd":
                systemd_services = services.services_list[service]["systemd_service"]
                if not isinstance(systemd_services, list):
                    systemd_services = [systemd_services]

                for service_name in systemd_services:
                    command = "sudo systemctl " + action + " " + service_name
                    logger.info(f"Executing: {command}")
                    await async_run(command)

            elif runtime == "docker":
                client = docker.from_env()  # type: ignore
                docker_services = services.services_list[service]["docker_service"]
                if not isinstance(docker_services, list):
                    docker_services = [docker_services]
                for service_name in docker_services:
                    logger.info(f'Executing: {action} on {service_name}')
                    try:
                        container = client.containers.get(service_name)
                        container.reload()
                        if action == "start":
                            container.start()
                        if action == "stop":
                            container.stop()
                        if action == "restart":
                            container.restart()
                        if action == "kill":
                            container.kill()
                    except (docker.errors.NotFound, docker.errors.APIError) as docker_error:  # type: ignore
                        logger.error(f"{docker_error}")
                        pass

            else:
                # The Nomad mode currently does not support shutting down services
                pass

    monitor_string = "action: " + action + "; services: " + form.get("services", "")
    monitor.send_webgui_event(monitor.w_events.SERVICE_CONTROL, request.user.display_name, monitor_string)
    return JSONResponse("{ }")


###################################################################################
# Error handlers
###################################################################################


@router.get("/error")
async def error(request):
    """
    An example error. Switch the `debug` setting to see either tracebacks or 500 pages.
    """
    raise RuntimeError("Oh no")


async def not_found(request, exc) -> Response:
    """
    Return an HTTP 404 page.
    """
    template = "404.html"
    context = {"request": request, "mercure_version": mercure_defs.VERSION}
    return templates.TemplateResponse(template, context, status_code=404)


async def server_error(request, exc) -> Response:
    """
    Return an HTTP 500 page.
    """
    if request.method == "GET":
        template = "500.html"
        context = {"request": request, "mercure_version": mercure_defs.VERSION}
        return templates.TemplateResponse(template, context, status_code=500)
    else:
        return JSONResponse({"error": "Internal server error"}, status_code=500)
exception_handlers = {
    404: not_found,
    500: server_error
}
app = None


class CSPMiddleware(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        scope["csp_nonce"] = secrets.token_urlsafe()
        await super().__call__(scope,receive,send)

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # Define your CSP policy here
        csp_policy = (
            f"script-src 'nonce-{request.scope['csp_nonce']}'; "
            "img-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-src 'self'; "
            "object-src 'none';"
        )

        response.headers["Content-Security-Policy"] = csp_policy
        return response


def create_app() -> Starlette:
    global app, DEBUG_MODE, SECRET_KEY
    app = Starlette(debug=DEBUG_MODE, lifespan=lifespan, exception_handlers=exception_handlers, routes=router)
    # Don't check the existence of the static folder because the wrong parent folder is used if the
    # source code is parsed by sphinx. This would raise an exception and lead to failure of sphinx.
    app.mount("/static", StaticFiles(directory="webinterface/statics", check_dir=False), name="static")
    app.add_middleware(AuthenticationMiddleware, backend=SessionAuthBackend())
    app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="mercure_session")
    app.add_middleware(CSPMiddleware)
    # print(app.state.csp_nonce)
    app.mount("/rules", rules.rules_app, name="rules")
    app.mount("/targets", targets.targets_app)
    app.mount("/modules", modules.modules_app)
    app.mount("/users", users.users_app)
    app.mount("/queue", queue.queue_app)
    app.mount("/api", api.api_app)
    app.mount("/tools", dashboards.dashboards_app)
    return app


###################################################################################
# Emergency error handler
###################################################################################


async def emergency_response(request) -> Response:
    """Shows emergency message about invalid configuration."""
    return PlainTextResponse(("ERROR: mercure configuration is invalid. "
                              "Check configuration and restart webgui service."),
                             status_code=500)


def launch_emergency_app() -> None:
    """Launches a minimal application to inform the user about the incorrect configuration"""
    # emergency_app = Starlette(debug=True)
    emergency_app = Router(
        [
            Route("/{whatever:path}", endpoint=emergency_response, methods=["GET", "POST"]),
        ]
    )
    uvicorn.run(emergency_app, host=WEBGUI_HOST, port=WEBGUI_PORT)


###################################################################################
# Entry function
###################################################################################


def main(args=sys.argv[1:]) -> None:
    global app, WEBGUI_HOST, WEBGUI_PORT, SECRET_KEY
    if "--reload" in args or os.getenv("MERCURE_ENV", "PROD").lower() == "dev":
        # start_reloader will only return in a monitored subprocess
        hupper.start_reloader("webgui.main")
        import logging

        logging.getLogger("watchdog").setLevel(logging.WARNING)
    try:
        read_webgui_config()
        services.read_services()
        config_ = config.read_config()
        users.read_users()
        success, error = helper.validate_folders(config_)
        if not success:
            raise ValueError(f"Invalid configuration folder structure: {error}")
        if str(SECRET_KEY) == "PutSomethingRandomHere":
            logger.error("You need to change the SECRET_KEY in configuration/webgui.env")
            raise Exception("Invalid or missing SECRET_KEY in webgui.env")
        app = create_app()
        uvicorn.run(app, host=WEBGUI_HOST, port=WEBGUI_PORT)
    except Exception as e:
        logger.error(e)
        logger.error("Cannot start service. Showing emergency message.")
        launch_emergency_app()
        logger.info("Going down.")
        sys.exit(1)


if __name__ == "__main__":
    main()
