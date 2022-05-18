"""
config.py
=============
Handling of configuration setting for the bookkeeper service
"""

# Standard python includes
import os
from typing import Any
import daiquiri

# Starlette-related includes
from starlette.config import Config


# Create local logger instance
logger = daiquiri.getLogger("config")


bookkeeper_config = Config((os.getenv("MERCURE_CONFIG_FOLDER") or "/opt/mercure/config") + "/bookkeeper.env")

BOOKKEEPER_PORT = bookkeeper_config("PORT", cast=int, default=8080)
BOOKKEEPER_HOST = bookkeeper_config("HOST", default="0.0.0.0")
DATABASE_URL = bookkeeper_config("DATABASE_URL", default="postgresql://mercure@localhost")
DATABASE_SCHEMA: Any = bookkeeper_config("DATABASE_SCHEMA", default=None)
DEBUG_MODE = bookkeeper_config("DEBUG", cast=bool, default=False)
API_KEY = None


def set_api_key() -> None:
    global API_KEY

    if API_KEY is None:
        from common.config import read_config

        try:
            c = read_config()
            API_KEY = c.bookkeeper_api_key
            if not API_KEY or API_KEY == "BOOKKEEPER_TOKEN_PLACEHOLDER":
                raise Exception("No API key set in config.json. Bookkeeper cannot function.")
        except (ResourceWarning, FileNotFoundError) as e:
            raise e
