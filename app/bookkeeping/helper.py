"""
helper.py
=========
Helper functions for the bookkeeper service.
"""

# Standard python includes
from typing import Any
import datetime
import json

# Starlette-related includes
from starlette.responses import JSONResponse


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(obj, datetime.date):
            return obj.strftime("%Y-%m-%d")
        else:
            try:
                dict_ = dict(obj)
            except TypeError:
                pass
            else:
                return dict_
            return super(CustomJSONEncoder, self).default(obj)


class CustomJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, cls=CustomJSONEncoder).encode("utf-8")

