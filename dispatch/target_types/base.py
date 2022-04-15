from common.types import TaskDispatch, TaskInfo, Rule, Target
import common.config as config
from subprocess import CalledProcessError, check_output

from pathlib import Path
import subprocess

logger = config.get_logger()


class TargetHandler:
    def __init__(self):
        pass

    def send_to_target(self, task_id, target: Target, dispatch_info: TaskDispatch, source_folder: Path):
        pass

    def handle_error(self, e, command):
        pass

    async def test_connection(self, target: Target, target_name: str):
        pass


class SubprocessTargetHandler(TargetHandler):
    def _create_command(self, target: Target, source_folder: Path):
        pass

    def send_to_target(self, task_id, target: Target, dispatch_info: TaskDispatch, source_folder: Path):
        command, opts = self._create_command(target, source_folder)
        try:
            logger.debug(f"Running command {command}")
            logger.info(f"Sending {source_folder} to target {dispatch_info.target_name}")
            result = check_output(command, stderr=subprocess.STDOUT, **opts)
            logger.debug(result.decode("utf-8"))
        except CalledProcessError as e:
            self.handle_error(e, command)
            raise
        return result
