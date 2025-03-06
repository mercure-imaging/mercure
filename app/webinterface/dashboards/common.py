import dataclasses
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import daiquiri
import pyfakefs
from common import config
from common.types import DicomTarget, DicomWebTarget
from decoRouter import Router as decoRouter
from rq import Queue, get_current_job
from rq.job import Job
from starlette.responses import JSONResponse, RedirectResponse
from webinterface.common import redis

from app.common import helper
from app.tests.getdcmtags import process_dicom

router = decoRouter()
logger = daiquiri.getLogger("dashboards")


@router.get("/")
async def index(request):
    return RedirectResponse(url="query")


class JSONErrorResponse(JSONResponse):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(content={"error": message}, status_code=status_code)


def invoke_getdcmtags(file: Path, node: Union[DicomTarget, DicomWebTarget, None], force_rule: Optional[str] = None):
    if not file.exists():
        raise FileNotFoundError(f"{file} does not exist")
    if not file.is_file():
        raise FileNotFoundError(f"{file} is not a file.")
    if isinstance(node, DicomTarget):
        sender_address = node.ip
        sender_aet = node.aet_target
        receiver_aet = node.aet_source
    elif isinstance(node, DicomWebTarget):
        sender_address = node.url
        sender_aet = "MERCURE-QUERY"
        receiver_aet = "MERCURE"
    else:
        sender_address = "localhost"
        sender_aet = "MERCURE"
        receiver_aet = "MERCURE"

    is_fake_fs = isinstance(Path, pyfakefs.fake_pathlib.FakePathlibPathModule)
    if is_fake_fs:  # running a test
        result = process_dicom(file, sender_address, sender_aet, receiver_aet,   # don't bother with bookkeeper
                               set_tags=[("mercureForceRule", force_rule)] if force_rule else [])
        if result is None:
            raise Exception("Failed to get DICOM tags from the file.")
        else:
            logger.info(f"Result {result}")
    else:
        try:
            invoke_with: list = [config.app_basepath / "bin" / "getdcmtags", file,
                                 sender_address, sender_aet, receiver_aet,
                                 config.mercure.bookkeeper, config.mercure.bookkeeper_api_key]
            if force_rule:
                invoke_with.extend(["--set-tag", f"mercureForceRule={force_rule}"])
            subprocess.check_output(invoke_with)
        except subprocess.CalledProcessError as e:
            logger.warning("Failed to invoke getdcmtags")
            logger.warning(e.output.decode() if e.output else "No stdout")
            logger.warning(e.stderr.decode() if e.stderr else "No stderr")
            raise
        except Exception:
            logger.warning(invoke_with)
            raise


@dataclass
class ClassBasedRQTask():
    parent: Optional[str] = None
    type: str = "unknown"
    _job: Optional[Job] = None
    _queue: str = ''

    @classmethod
    def queue(cls, connection=None) -> Queue:
        return Queue(cls._queue, connection=(connection or redis))

    def create_job(self, connection, rq_options={}, **kwargs) -> Job:
        fields = dataclasses.fields(self)
        meta = {field.name: getattr(self, field.name) for field in fields}
        return Job.create(self._execute, connection=connection, kwargs=kwargs, meta=meta, **rq_options)

    @classmethod
    def _execute(cls, **kwargs) -> Any:
        job = get_current_job()
        if not job:
            raise Exception("No current job")
        fields = dataclasses.fields(cls)
        meta = {}
        for f in fields:
            if f.name in job.meta and not f.name.startswith('_'):
                meta[f.name] = job.meta[f.name]
        result = cls(**meta, _job=job).execute(**kwargs)
        if result is None:
            return b""
        return result

    def execute(self, *args, **kwargs) -> Any:
        pass

    @staticmethod
    def move_to_destination(path: str, destination: Optional[str], job_id: str,
                            node: Union[DicomTarget, DicomWebTarget], force_rule: Optional[str] = None) -> None:
        if destination is not None:
            dest_folder: Path = Path(destination) / job_id
            dest_folder.mkdir(exist_ok=True)
            logger.info(f"moving {path} to {dest_folder}")
            lock = helper.FileLock(dest_folder / ".mercure-sending")
            shutil.move(path, dest_folder)
            (dest_folder / ".complete").touch()
            lock.free()
            return

        config.read_config()
        moved_files = []
        try:
            for p in Path(path).glob("**/*"):
                if not p.is_file():
                    continue
                # if p.suffix == ".dcm":
                #     name = p.stem
                # else:
                #     name = p.name
                logger.debug(f"Moving {p} to {config.mercure.incoming_folder}/{p.name}")
                dest_name = Path(config.mercure.incoming_folder) / p.name
                shutil.move(str(p), dest_name)  # Move the file to incoming folder
                moved_files.append(dest_name)
                invoke_getdcmtags(Path(config.mercure.incoming_folder) / p.name, node, force_rule)
        except Exception:
            for file in moved_files:
                try:
                    file.unlink()
                except Exception:
                    pass
            raise
        # tree(config.mercure.incoming_folder)
        shutil.rmtree(path)
