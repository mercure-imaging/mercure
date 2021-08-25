import os
import common.config as config


def load_config(fs, extra) -> None:
    config_path = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/data/test_config.json")
    fs.add_real_file(config_path, target_path=config.configuration_filename, read_only=False)
    for k in ["incoming", "studies", "outgoing", "success", "error", "discard", "processing"]:
        fs.create_dir(f"/var/{k}")
    config.read_config()
    config.mercure = {**config.mercure, **extra}  # type: ignore
    config.save_config()
