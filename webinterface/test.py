"""
queue.py
========
Queue page for the graphical user interface of mercure.
"""

# Standard python includes
import os
from pathlib import Path
import json
import daiquiri
from typing import Dict
import collections

# Starlette-related includes
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.authentication import requires

# App-specific includes
import common.config as config
from common.constants import mercure_defs, mercure_names
from webinterface.common import get_user_information
from webinterface.common import templates
from common.types import Task


logger = daiquiri.getLogger("test")


test_app = Starlette()


@test_app.route("/", methods=["GET"])
@requires("authenticated", redirect="login")
async def index(request):
    template = "test.html"
    context = {
        "request": request,
        "mercure_version": mercure_defs.VERSION,
        "page": "test",
    }
    context.update(get_user_information(request))
    return templates.TemplateResponse(template, context)
