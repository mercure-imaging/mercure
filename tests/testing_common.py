"""
testing_common.py
=================
"""
import os

import common.config as config
from common.types import Config


def load_config(fs, extra) -> Config:
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/data/test_config.json")
    fs.add_real_file(config_path, target_path=config.configuration_filename, read_only=False)
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing"]:
        fs.create_dir(f"/var/{k}")
    config.read_config()
    config.mercure = Config(**{**config.mercure.dict(), **extra})  #   # type: ignore
    config.save_config()
    return config.mercure
