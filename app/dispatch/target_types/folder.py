"""
folder.py
=========
"""

import shutil
import uuid
from pathlib import Path

import common.config as config
from common.types import FolderTarget, Task, TaskDispatch

from .base import TargetHandler
from .registry import handler_for

logger = config.get_logger()


@handler_for(FolderTarget)
class FolderTargetTargetHandler(TargetHandler[FolderTarget]):
    view_template = "targets/folder.html"
    edit_template = "targets/folder-edit.html"
    display_name = "Folder"
    icon = "fa-folder"

    def send_to_target(self, task_id: str, target: FolderTarget, dispatch_info: TaskDispatch,
                       source_folder: Path, task: Task) -> str:
        # send dicoms in source-folder to target folder
        new_folder = Path(target.folder) / str(uuid.uuid4())
        if target.file_filter:
            shutil.copytree(source_folder, new_folder, ignore=shutil.ignore_patterns(*target.file_filter.split(",")))
        else:
            shutil.copytree(source_folder, new_folder)
        (new_folder / ".complete").touch()
        logger.info(f"Copied {source_folder} to {new_folder}")
        return ""

    def from_form(self, form: dict, factory, current_target: FolderTarget) -> FolderTarget:
        return FolderTarget(**form)

    async def test_connection(self, target: FolderTarget, target_name: str):
        result = {}
        result["Folder exists"] = Path(target.folder).exists()
        try:
            (Path(target.folder) / ".test").touch()
            result["Folder is writeable"] = True
            (Path(target.folder) / ".test").unlink()
        except Exception as e:
            print(e)
            result["Folder is writeable"] = False
        return result
