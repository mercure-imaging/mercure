"""
modules.py
==========
Modules page for the graphical user interface of mercure.
"""

# Standard python includes
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import docker
import httpx
from decoRouter import Router as decoRouter

# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse

# App-specific includes
import common.config as config
import common.helper as helper
from common.constants import mercure_names
from common.types import Module
from webinterface.common import redis, strip_untrusted, templates

router = decoRouter()
logger = config.get_logger()

# In-memory cache fallback for online modules only
_modules_cache: Dict[str, Any] = {"data": None, "timestamp": None}
CACHE_TTL_SECONDS = 3600  # 1 hour
CACHE_KEY = "mercure:online_modules"


###################################################################################
# Common functions
###################################################################################


class ServerErrorResponse(PlainTextResponse):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.status_code = 500


class BadRequestResponse(PlainTextResponse):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.status_code = 400


async def save_module(form, name) -> None:
    """Save the settings for the module with the given name."""

    # Ensure that the module settings are valid. Should happen on the client side too, but can't hurt to check again.

    try:
        new_settings: Dict = json.loads(form.get("settings", "{}"))
    except Exception:
        new_settings = {}
    config.mercure.modules[name] = Module(
        docker_tag=form.get("docker_tag", "").strip(),
        additional_volumes=form.get("additional_volumes", ""),
        environment=form.get("environment", ""),
        docker_arguments=form.get("docker_arguments", ""),
        settings=new_settings,
        contact=strip_untrusted(form.get("contact", "")),
        comment=strip_untrusted(form.get("comment", "")),
        constraints=form.get("constraints", ""),
        resources=form.get("resources", ""),
        requires_root=form.get("requires_root", False)
        or form.get("container_type", "mercure") == "monai",
        requires_persistence=form.get("requires_persistence", False),
    )
    config.save_config()


###################################################################################
# Modules endpoints
###################################################################################


@router.get("/")
@requires("authenticated", redirect="login")
async def show_modules(request):
    """Shows all installed modules"""

    try:
        config.read_config()
    except Exception:
        return PlainTextResponse(
            "Configuration is being updated. Try again in a minute."
        )

    used_modules = {}
    for rule in config.mercure.rules:
        used_module = config.mercure.rules[rule].get("processing_module", "NONE")
        if isinstance(used_module, list):
            for m in used_module:
                used_modules[m] = rule
        else:
            used_modules[used_module] = rule

    template = "modules.html"
    context = {
        "request": request,
        "page": "modules",
        "modules": config.mercure.modules,
        "used_modules": used_modules,
    }
    return templates.TemplateResponse(template, context)


@router.post("/")
@requires(["authenticated", "admin"], redirect="login")
async def add_module(request):
    """Creates a new module and forwards the user to the module edit page."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse(
            "Configuration is being updated. Try again in a minute."
        )

    form = dict(await request.form())
    name = form.get("name", "")
    form["name"] = name.strip()
    form["docker_tag"] = form["docker_tag"].strip()

    if not re.fullmatch("[0-9a-zA-Z_\-]+", name):
        return BadRequestResponse("Invalid module name provided.")

    if not re.fullmatch("[a-zA-Z0-9-:/_.@]+", form["docker_tag"]):
        return BadRequestResponse("Invalid docker_tag provided.")

    if name in config.mercure.modules:
        return BadRequestResponse("A module with this name already exists.")

    client = docker.from_env()  # type: ignore
    try:
        client.images.get(form["docker_tag"])
    except docker.errors.ImageNotFound:
        try:
            client.images.get_registry_data(form["docker_tag"])
        except docker.errors.APIError as e:
            if e.response.status_code == 403:
                return ServerErrorResponse(
                    "A Docker container with this tag does not exist locally or in the Docker Hub registry."
                )
            else:
                logger.exception(e)
                return ServerErrorResponse(
                    f"Failed to retrieve Docker Registry data about this docker tag: {e}"
                )
        except Exception as e:
            logger.exception(e)
            return ServerErrorResponse(
                f"Unexpected error retrieving Docker Registry data about this docker tag: {e}"
            )
    except docker.errors.APIError as e:
        logger.exception(e)
        return ServerErrorResponse(
            f"Unable to read container list: {e}. \n Check server logs, Docker installation, and any firewall settings."
        )
    except Exception as e:
        logger.exception(e)
        return ServerErrorResponse(
            f"Unexpected error: {e}. \n Check server logs, Docker installation, and any firewall settings."
        )
    if (
        form["container_type"] == "monai"
        and config.mercure.support_root_modules is not True
    ):
        return BadRequestResponse(
            "MONAI modules must run as root user, but the setting 'Support Root Modules' "
            "is disabled in the mercure configuration."
            "Enable it on the Configuration page before installing MONAI modules."
        )
    # logger.info(f'Created rule {name}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, name)
    try:
        await save_module(form, name)
    except Exception as e:
        logger.exception(e)
        return ServerErrorResponse(f"Unexpected error while saving new module. {e}")

    return PlainTextResponse(headers={"HX-Refresh": "true"})


@router.get("/edit/{module}")
@requires("authenticated", redirect="login")
async def edit_module(request):
    """Show the module edit page for the given module name."""
    module = request.path_params["module"]
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse(
            "Configuration is being updated. Try again in a minute."
        )

    settings_string = ""
    if config.mercure.modules[module].settings:
        settings_string = json.dumps(
            config.mercure.modules[module].settings, indent=4, sort_keys=False
        )

    module_data = config.mercure.modules[module]
    module_persistence_name = module_data.get("persistence_folder_name", "") or module
    module_mount_source = (
        Path(config.mercure.persistence_folder) / module_persistence_name
    )

    module_persistence_file = "{}"
    if Path(module_mount_source).exists():
        try:
            with open(Path(module_mount_source) / "persistence.json") as f:
                module_persistence_file = json.dumps(
                    json.load(f), indent=4, sort_keys=False
                )
        except Exception:
            logger.error(f"Unable to read persistence.json at {module_mount_source}.")

    runtime = helper.get_runner()

    template = "modules_edit.html"
    context = {
        "request": request,
        "page": "modules",
        "module": config.mercure.modules[module],
        "module_name": module,
        "settings": settings_string,
        "runtime": runtime,
        "support_root_modules": config.mercure.support_root_modules,
        "module_persistence_file": module_persistence_file,
        "persistence_folder": module_mount_source,
    }
    return templates.TemplateResponse(template, context)


@router.post("/edit/{module}")
@requires(["authenticated", "admin"], redirect="login")
async def edit_module_POST(request):
    """Save the settings for the given module name."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse(
            "Configuration is being updated. Try again in a minute."
        )

    form = dict(await request.form())

    name = request.path_params["module"]
    if name not in config.mercure.modules:
        return PlainTextResponse("Invalid module name - perhaps it was deleted?")

    if not re.fullmatch("[0-9a-zA-Z_\-]+", name):
        return BadRequestResponse("Invalid module name provided.")

    if not re.fullmatch("[a-zA-Z0-9-:/_.@]+", form["docker_tag"]):
        return BadRequestResponse("Invalid docker_tag provided.")

    try:
        await save_module(form, name)
    except Exception as e:
        logger.exception(e)
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    return RedirectResponse(url="/modules/", status_code=303)


@router.post("/edit/{module}/save_persistence")
@requires(["authenticated", "admin"], redirect="login")
async def save_persistence_file(request):
    """Saves the persistence file for the given module."""
    name = request.path_params["module"]
    data = await request.json()

    if name not in config.mercure.modules:
        return PlainTextResponse("Invalid module name - perhaps it was deleted?")

    if not re.fullmatch("[0-9a-zA-Z_\-]+", name):
        return BadRequestResponse("Invalid module name provided.")

    module_data = config.mercure.modules[name]
    module_persistence_name = module_data.get("persistence_folder_name", "") or name
    module_mount_source = (
        Path(config.mercure.persistence_folder) / module_persistence_name
    )

    try:
        os.makedirs(module_mount_source, exist_ok=True)
    except Exception:
        logger.error(f"Unable to create persistence folder {module_mount_source}")
        return JSONResponse({"code": 1, "message": "Unable to write persistence file."})
    if Path(module_mount_source).exists():
        lock_exists = any(
            f.endswith(mercure_names.LOCK)
            and os.path.isfile(os.path.join(module_mount_source, f))
            for f in os.listdir(module_mount_source)
        )
        if lock_exists:
            logger.info(f"Persistence for module {name} is locked. Skipping update!")
            return JSONResponse(
                {
                    "code": 3,
                    "message": "Cannot update the persistence file while module is running. Try again later.",
                }
            )

        try:
            # check if the saved persistence file matches old persistence file from the form (UI)
            if Path(module_mount_source / "persistence.json").exists():
                with open(Path(module_mount_source) / "persistence.json", "r") as f:
                    saved_persistence_file = json.load(f)
                if data.get("old_persistence_file", "{}") != saved_persistence_file:
                    logger.error(
                        f"Old persistence file does not match the saved one at {module_mount_source}. Skipping update!"
                    )
                    return JSONResponse(
                        {
                            "code": 0,
                            "message": "The persistence file has changed on disk since it was last loaded, so changes cannot be saved. Please reload the persistence file and make your update again. If this happens repeatedly, suspend processing before manually updating the persistence file.",
                        }
                    )
            with open(Path(module_mount_source) / "persistence.json", "w") as f:
                json.dump(data.get("persistence_file", "{}"), f, indent=4)
        except Exception:
            logger.error(f"Unable to write persistence.json at {module_mount_source}.")
            return JSONResponse(
                {"code": 1, "message": "Unable to write persistence file."}
            )
    return JSONResponse({"code": 2, "message": "Persistence file saved successfully."})


@router.get("/edit/{module}/refresh_persistence")
@requires("authenticated", redirect="login")
async def refresh_persistence_file(request):
    """Refreshes the persistence file for the given module."""
    name = request.path_params["module"]

    if name not in config.mercure.modules:
        return PlainTextResponse("Invalid module name - perhaps it was deleted?")

    if not re.fullmatch("[0-9a-zA-Z_\-]+", name):
        return BadRequestResponse("Invalid module name provided.")

    module_data = config.mercure.modules[name]
    module_persistence_name = module_data.get("persistence_folder_name", "") or name
    module_mount_source = (
        Path(config.mercure.persistence_folder) / module_persistence_name
    )

    if Path(module_mount_source).exists():
        try:
            with open(Path(module_mount_source) / "persistence.json") as f:
                persistence_file = json.dumps(json.load(f), indent=4, sort_keys=False)
        except Exception:
            logger.error(f"Unable to read persistence.json at {module_mount_source}.")
            persistence_file = "{}"
    else:
        persistence_file = "{}"
    return JSONResponse({"persistence_file": persistence_file})


@router.post("/delete/{module}")
@requires(["authenticated", "admin"], redirect="login")
async def delete_module(request):
    """Deletes the module with the given module name."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse(
            "Configuration is being updated. Try again in a minute."
        )

    name = request.path_params["module"]
    if name in config.mercure.modules:
        del config.mercure.modules[name]

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")
    # logger.info(f'Created rule {newrule}')
    # monitor.send_webgui_event(monitor.w_events.RULE_CREATE, request.user.display_name, newrule)
    return RedirectResponse(url="/modules", status_code=303)


async def _fetch_online_modules() -> Optional[str]:
    """Fetch module registry from GitHub. Returns JSON string or None on error."""
    GITHUB_REPO = "mercure-imaging/modules-registry"
    MODULES_JSON_PATH = "modules.json"
    GITHUB_API_URL = (
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MODULES_JSON_PATH}"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                GITHUB_API_URL, headers={"User-Agent": "mercure-imaging"}
            )
            if response.status_code == 200:
                content = response.json()
                if "content" in content:
                    base64_content = content["content"]
                    modules_data = base64.b64decode(base64_content).decode("utf-8")
                    return modules_data
            elif response.status_code == 403:
                logger.warning("GitHub API rate limit exceeded")
            else:
                logger.warning(
                    f"Failed to fetch modules from GitHub: {response.status_code}"
                )
    except Exception as e:
        logger.exception(f"Error fetching modules from GitHub: {e}")

    return None


def _fetch_local_images() -> Optional[List[str]]:
    """Fetch all locally installed Docker images. Returns list of image tags."""
    installed_images = []
    try:
        docker_client = docker.from_env()
        for image in docker_client.images.list():
            if image.tags:
                installed_images.append(image.tags[0])
    except Exception as e:
        logger.error(f"Error fetching installed docker images: {e}")
        return None

    return sorted(installed_images)


def _get_cached_online_modules() -> Optional[str]:
    """Get cached online modules from Redis or in-memory cache. Returns JSON string or None."""
    try:
        # Try Redis first
        cached_data = redis.get(CACHE_KEY)
        if cached_data:
            # Redis returns bytes, need to decode to string
            if isinstance(cached_data, bytes):
                cached_str = cached_data.decode("utf-8")
            else:
                cached_str = str(cached_data)

            logger.debug("Retrieved online modules from Redis cache")
            return cached_str
    except Exception as e:
        logger.warning(f"Redis cache read failed: {e}")

    # Fallback to in-memory cache
    if _modules_cache["data"] and _modules_cache["timestamp"]:
        age = time.time() - _modules_cache["timestamp"]
        if age < CACHE_TTL_SECONDS:
            logger.debug("Retrieved online modules from in-memory cache")
            return _modules_cache["data"]

    return None


def _set_cached_online_modules(online_modules: str) -> None:
    """Store online modules in both Redis and in-memory cache."""
    # Try to cache in Redis
    try:
        redis.setex(CACHE_KEY, CACHE_TTL_SECONDS, online_modules)
        logger.debug("Cached online modules in Redis")
    except Exception as e:
        logger.warning(f"Redis cache write failed: {e}")

    # Always cache in memory as fallback
    _modules_cache["data"] = online_modules
    _modules_cache["timestamp"] = time.time()
    logger.debug("Cached online modules in memory")


@router.get("/fetch_registry")
@requires("authenticated", redirect="login")
async def fetch_modules(request):
    """Fetch the list of available modules from the modules registry and local images.
    Online modules are cached for 1 hour in Redis (or in-memory if Redis unavailable).
    Local images are fetched fresh each time."""

    # Check cache for online modules
    online_modules = _get_cached_online_modules()
    # Always fetch local images fresh
    local_images = _fetch_local_images()
    warning = None
    if local_images is None:
        warning = "Error querying Docker daemon for local image list."

    # Cache miss or expired - fetch from GitHub
    if online_modules is None:
        online_modules = await _fetch_online_modules()
        if online_modules is None:
            return JSONResponse(
                {
                    "online_modules": [],
                    "installed_images": local_images,
                    "warning": "Could not load online module list.",
                }
            )
        # Cache the online modules
        _set_cached_online_modules(online_modules)

    return JSONResponse(
        {
            "online_modules": json.loads(online_modules),
            "installed_images": local_images or [],
            "warning": warning,
        }
    )


modules_app = Starlette(routes=router)
