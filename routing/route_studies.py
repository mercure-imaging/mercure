import os
from pathlib import Path
import uuid
import json
import shutil
import daiquiri

# App-specific includes
import common.config as config
import common.rule_evaluation as rule_evaluation
import common.monitor as monitor
import common.helper as helper
from common.constants import mercure_defs, mercure_names, mercure_actions, mercure_rule, mercure_config, mercure_options


logger = daiquiri.getLogger("route_series")


def route_studies():
    # TODO
    pass
