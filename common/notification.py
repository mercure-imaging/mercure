import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri

# App-specific includes
import common.config as config
import common.monitor as monitor
import common.helper as helper
from common.constants import mercure_defs, mercure_names, mercure_sections, mercure_rule, mercure_config, mercure_options


logger = daiquiri.getLogger("notification")


def send_webhook(url, payload, event):
    # TODO
    pass


