import dataclasses
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
from rq.job import Dependency, Job, JobStatus
from starlette.responses import JSONResponse, RedirectResponse
from tests.getdcmtags import process_dicom
from webinterface.common import redis

router = decoRouter()
logger = daiquiri.getLogger("dashboards")


@router.get("/")
async def index(request):
    return RedirectResponse(url="query")


class JSONErrorResponse(JSONResponse):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(content={"error": message}, status_code=status_code)


def invoke_getdcmtags(file: Path, node: Union[DicomTarget, DicomWebTarget, None], force_rule: Optional[str] = None):
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
