from dataclasses import dataclass

from pydicom import Dataset
from common.types import Task, TaskDispatch
import common.config as config
from subprocess import CalledProcessError, check_output
from typing import Any, Dict, Generator, List, TypeVar, Generic
from pydicom.datadict import tag_for_keyword

from pathlib import Path
import subprocess

logger = config.get_logger()

TargetTypeVar = TypeVar("TargetTypeVar")


@dataclass
class ProgressInfo():
    completed: int = 0
    remaining: int = 0
    progress: str = ""


class TargetHandler(Generic[TargetTypeVar]):
    test_template = "targets/base-test.html"
    can_pull = False

    def __init__(self):
        pass

    @property
    def info_short(self) -> str:
        return ""

    def send_to_target(
        self,
        task_id: str,
        target: TargetTypeVar,
        dispatch_info: TaskDispatch,
        source_folder: Path,
        task: Task,
    ) -> str:
        return ""

    class NoSuchTagException(Exception):
        pass

    def get_from_target(self, target: TargetTypeVar, accession: str,
                        search_filters: Dict[str, List[str]], destination_path: str) -> Generator[ProgressInfo, None, None]:
        raise Exception()

    def find_from_target(self, target: TargetTypeVar, accession: str, search_filters: Dict[str, List[str]]) -> List[Dataset]:
        if self is TargetHandler:
            raise Exception("This method should be overridden by a subclass")
        for t in search_filters.keys():
            if not tag_for_keyword(t):
                raise TargetHandler.NoSuchTagException(f"Invalid search filter: no such tag '{t}'")
        return []

    def handle_error(self, e, command) -> None:
        pass

    async def test_connection(self, target: TargetTypeVar, target_name: str) -> dict:
        return {}

    def from_form(self, form: dict, factory: Any, current_target: TargetTypeVar) -> Any:
        return factory(**form)


class SubprocessTargetHandler(TargetHandler[TargetTypeVar]):
    def _create_command(self, target: TargetTypeVar, source_folder: Path, task: Task):
        return ("", {})

    def send_to_target(
        self,
        task_id: str,
        target: TargetTypeVar,
        dispatch_info: TaskDispatch,
        source_folder: Path,
        task: Task,
    ) -> str:
        commands, opts = self._create_command(target, source_folder, task)
        if not isinstance(commands[0], list):
            commands = [commands]
        result = ""
        logger.info(f"Sending {source_folder} to target {dispatch_info.target_name}")
        for command in commands:
            try:
                logger.info(f"Running command {' '.join(command)}")
                output = check_output(
                    command, encoding="utf-8", stderr=subprocess.STDOUT, **opts
                )
                result += output
                logger.info(output)
            # return result  # type: ignore  # Mypy doesn't know that check_output returns a string here?
            except CalledProcessError as e:
                self.handle_error(e, command)
                raise
        return result

    def handle_error(self, e: CalledProcessError, command) -> None:
        logger.error(e.output)
        logger.error(f"Failed. Command exited with value {e.returncode}: \n {command}")
