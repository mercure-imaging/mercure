"""
config.py
=============
Handling of configuration setting for the bookkeeper service
"""

# Standard python includes
import os
from typing import Optional

import daiquiri
# Starlette-related includes
from starlette.config import Config

# Create local logger instance
logger = daiquiri.getLogger("config")
bookkeeper_config: Config
config_filename: str = (os.getenv("MERCURE_CONFIG_FOLDER") or "/opt/mercure/config") + "/bookkeeper.env"
DATABASE_URL: str
BOOKKEEPER_PORT: int
BOOKKEEPER_HOST: str
DATABASE_SCHEMA: Optional[str]
API_KEY: Optional[str]
DEBUG_MODE: bool


def read_bookkeeper_config() -> Config:
    global bookkeeper_config, BOOKKEEPER_PORT, BOOKKEEPER_HOST, DATABASE_URL, DATABASE_SCHEMA, DEBUG_MODE, API_KEY
    bookkeeper_config = Config(config_filename)

    BOOKKEEPER_PORT = bookkeeper_config("PORT", cast=int, default=8080)
    BOOKKEEPER_HOST = bookkeeper_config("HOST", default="0.0.0.0")
    DATABASE_URL = bookkeeper_config("DATABASE_URL", default="postgresql://mercure@localhost")
    DATABASE_SCHEMA = bookkeeper_config("DATABASE_SCHEMA", default=None)
    DEBUG_MODE = bookkeeper_config("DEBUG", cast=bool, default=False)
    API_KEY = None
    return bookkeeper_config


def set_api_key() -> None:
    global API_KEY

    if API_KEY is None:
        from common.config import read_config

        try:
            c = read_config()
            API_KEY = c.bookkeeper_api_key
            if not API_KEY or API_KEY == "BOOKKEEPER_TOKEN_PLACEHOLDER":
                raise Exception("No API key set in mercure.json or value"
                                " unchanged from placeholder. Bookkeeper cannot function.")
        except (ResourceWarning, FileNotFoundError) as e:
            raise e
