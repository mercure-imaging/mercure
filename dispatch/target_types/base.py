from common.types import TaskDispatch, TaskInfo, Rule, Target
import common.config as config
from subprocess import CalledProcessError, check_output
from starlette.responses import JSONResponse
from typing import Any, TypeVar, Generic, cast

from pathlib import Path
import subprocess

logger = config.get_logger()

TargetTypeVar = TypeVar("TargetTypeVar")


class TargetHandler(Generic[TargetTypeVar]):
    test_template = "targets/base-test.html"

    def __init__(self):
        pass

    def send_to_target(
        self, task_id: str, target: TargetTypeVar, dispatch_info: TaskDispatch, source_folder: Path
    ) -> str:
        return ""

    def handle_error(self, e, command) -> None:
        pass

    async def test_connection(self, target: TargetTypeVar, target_name: str) -> dict:
        return {}

    def from_form(self, form: dict, factory: Any, current_target: TargetTypeVar) -> Any:
        return factory(**form)


class SubprocessTargetHandler(TargetHandler[TargetTypeVar]):
    def _create_command(self, target: TargetTypeVar, source_folder: Path):
        return ("",{})

    def send_to_target(
        self, task_id: str, target: TargetTypeVar, dispatch_info: TaskDispatch, source_folder: Path
    ) -> str:
        command, opts = self._create_command(target, source_folder)
        try:
            logger.debug(f"Running command {command}")
            logger.info(f"Sending {source_folder} to target {dispatch_info.target_name}")
            result = check_output(command, encoding="utf-8", stderr=subprocess.STDOUT, **opts)
            return result  # type: ignore  # Mypy doesn't know that check_output returns a string here?
        except CalledProcessError as e:
            self.handle_error(e, command)
            raise

    def handle_error(self, e, command) -> None:
        logger.error(f"Failed. Command exited with value {e.returncode}: \n {command}")
