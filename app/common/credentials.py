"""
credentials.py
==============
Load environment variables from systemd credential files.

When a service uses LoadCredential=, systemd places files in a secure directory
and sets CREDENTIALS_DIRECTORY to its path. This module reads any .env files
found there and injects their key=value pairs into os.environ, equivalent to
systemd's EnvironmentFile= directive.

Call load_credentials() early in each service entrypoint, before any module
reads os.environ (e.g. before importing webinterface.common).
"""

import os
from pathlib import Path


def load_credentials() -> None:
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if not cred_dir:
        return

    cred_path = Path(cred_dir)
    if not cred_path.is_dir():
        return

    for env_file in sorted(cred_path.glob("*.env")):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    os.environ[key] = value
