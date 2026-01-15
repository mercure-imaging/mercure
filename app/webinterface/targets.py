"""
targets.py
==========
Targets page for the graphical user interface of mercure.
"""

# Standard python includes
import json
import os
import shutil
from pathlib import Path
from typing import Union

# App-specific includes
import common.config as config
import common.monitor as monitor
import dispatch.target_types as target_types
from common.types import DicomTarget
from decoRouter import Router as decoRouter
# Starlette-related includes
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from webinterface.common import get_user_information, templates

router = decoRouter()

logger = config.get_logger()

# Directory for storing GCP service account keys
GCP_KEYS_DIR = Path("/opt/mercure/config/gcp-keys")


###################################################################################
# Targets endpoints
###################################################################################


@router.get("/")
@requires("authenticated", redirect="login")
async def show_targets(request) -> Response:
    """Shows all configured targets."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    used_targets = {}
    for rule in config.mercure.rules:
        if isinstance(config.mercure.rules[rule].target, str):
            used_target = config.mercure.rules[rule].get("target", "NONE")
            used_targets[used_target] = rule
        else:
            for item in config.mercure.rules[rule].target:
                used_targets[item] = rule

    template = "targets.html"
    context = {
        "request": request,
        "page": "targets",
        "targets": config.mercure.targets,
        "used_targets": used_targets,
        "get_target_handler": target_types.get_handler,
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/")
@requires(["authenticated", "admin"], redirect="login")
async def add_target(request) -> Response:
    """Creates a new target."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    form = dict(await request.form())

    newtarget = form.get("name", "")
    if newtarget in config.mercure.targets:
        return PlainTextResponse("Target already exists.")

    config.mercure.targets[newtarget] = DicomTarget(ip="", port="", aet_target="")

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Created target {newtarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_CREATE, request.user.display_name, newtarget)
    return RedirectResponse(url="/targets/edit/" + newtarget, status_code=303)


@router.get("/edit/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_edit(request) -> Response:
    """Shows the edit page for the given target."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edittarget = request.path_params["target"]

    if edittarget not in config.mercure.targets:
        return RedirectResponse(url="/targets", status_code=303)

    template = "targets_edit.html"
    context = {
        "request": request,
        "page": "targets",
        "targets": config.mercure.targets,
        "edittarget": edittarget,
        "get_target_handler": target_types.get_handler,
        "target_types": target_types.target_types(),
        "target_names": [
            k.get_name()
            for k in target_types.target_types()
            if k.get_name() != "dummy" or config.mercure.features.get("dummy_target")
        ],
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)


@router.post("/edit/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_edit_post(request) -> Union[RedirectResponse, PlainTextResponse]:
    """Updates the given target using the form values posted with the request."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    edittarget: str = request.path_params["target"]
    form = dict(await request.form())

    if edittarget not in config.mercure.targets:
        return PlainTextResponse("Target does not exist anymore.")

    TargetType = target_types.type_from_name(form["target_type"])

    config.mercure.targets[edittarget] = target_types.get_handler(form["target_type"]).from_form(
        form, TargetType, config.mercure.targets[edittarget]
    )

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Edited target {edittarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_EDIT, request.user.display_name, edittarget)
    return RedirectResponse(url="/targets", status_code=303)


@router.post("/delete/{target}")
@requires(["authenticated", "admin"], redirect="login")
async def targets_delete_post(request) -> Response:
    """Deletes the given target."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    deletetarget = request.path_params["target"]

    if deletetarget in config.mercure.targets:
        # If target has a GCP key file, optionally delete it
        target = config.mercure.targets[deletetarget]
        if hasattr(target, 'gcp_service_account_json_path') and target.gcp_service_account_json_path:
            try:
                key_path = Path(target.gcp_service_account_json_path)
                if key_path.exists():
                    key_path.unlink()
                    logger.info(f"Deleted GCP key file: {key_path}")
            except Exception as e:
                logger.warning(f"Could not delete GCP key file: {e}")
        
        del config.mercure.targets[deletetarget]

    try:
        config.save_config()
    except Exception:
        return PlainTextResponse("ERROR: Unable to write configuration. Try again.")

    logger.info(f"Deleted target {deletetarget}")
    monitor.send_webgui_event(monitor.w_events.TARGET_DELETE, request.user.display_name, deletetarget)
    return RedirectResponse(url="/targets", status_code=303)


@router.post("/test/{target}")
@requires(["authenticated"], redirect="login")
async def targets_test_post(request) -> Response:
    """Tests the connectivity of the given target by executing ping and c-echo requests."""
    try:
        config.read_config()
    except Exception:
        return PlainTextResponse("Configuration is being updated. Try again in a minute.")

    testtarget = request.path_params["target"]
    target = config.mercure.targets[testtarget]

    handler = target_types.get_handler(target)
    result = await handler.test_connection(target, testtarget)
    return templates.TemplateResponse(handler.test_template, {"request": request, "result": result})


@router.post("/upload_gcp_key")
@requires(["authenticated", "admin"], redirect="login")
async def upload_gcp_key(request) -> JSONResponse:
    """
    Handles upload of GCP service account JSON key file.
    Saves the file to /opt/mercure/config/gcp-keys/ directory.
    """
    try:
        # Ensure GCP keys directory exists
        GCP_KEYS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        
        # Parse form data
        form = await request.form()
        uploaded_file = form.get("gcp_json_file")
        target_name = form.get("target_name", "unknown")
        
        if not uploaded_file:
            return JSONResponse(
                {"success": False, "error": "No file provided"},
                status_code=400
            )
        
        # Validate file is JSON
        if not uploaded_file.filename.endswith('.json'):
            return JSONResponse(
                {"success": False, "error": "File must be a JSON file"},
                status_code=400
            )
        
        # Read and validate JSON content
        file_content = await uploaded_file.read()
        try:
            json_data = json.loads(file_content)
            
            # Basic validation of service account structure
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
            missing_fields = [field for field in required_fields if field not in json_data]
            
            if missing_fields:
                return JSONResponse(
                    {
                        "success": False, 
                        "error": f"Invalid service account JSON. Missing fields: {', '.join(missing_fields)}"
                    },
                    status_code=400
                )
            
            if json_data.get('type') != 'service_account':
                return JSONResponse(
                    {"success": False, "error": "JSON file must be a service account key"},
                    status_code=400
                )
                
        except json.JSONDecodeError as e:
            return JSONResponse(
                {"success": False, "error": f"Invalid JSON file: {str(e)}"},
                status_code=400
            )
        
        # Generate safe filename based on target name and original filename
        safe_target_name = "".join(c for c in target_name if c.isalnum() or c in ('-', '_'))
        original_name = Path(uploaded_file.filename).stem
        safe_original_name = "".join(c for c in original_name if c.isalnum() or c in ('-', '_'))
        
        filename = f"{safe_target_name}_{safe_original_name}.json"
        file_path = GCP_KEYS_DIR / filename
        
        # Check if file already exists and create backup
        if file_path.exists():
            backup_path = GCP_KEYS_DIR / f"{filename}.backup"
            shutil.copy2(file_path, backup_path)
            logger.info(f"Created backup of existing key: {backup_path}")
        
        # Write file with restricted permissions
        file_path.write_bytes(file_content)
        file_path.chmod(0o600)  # Read/write for owner only
        
        logger.info(f"Uploaded GCP service account key: {file_path}")
        monitor.send_webgui_event(
            monitor.w_events.TARGET_EDIT, 
            request.user.display_name, 
            f"Uploaded GCP key for {target_name}"
        )
        
        return JSONResponse({
            "success": True,
            "file_path": str(file_path),
            "message": "File uploaded successfully"
        })
        
    except Exception as e:
        logger.error(f"Error uploading GCP key: {e}")
        return JSONResponse(
            {"success": False, "error": f"Server error: {str(e)}"},
            status_code=500
        )


targets_app = Starlette(routes=router)