
from dataclasses import dataclass
import dataclasses
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Generator, List, Optional, Tuple, Union, cast
import typing

from dicomweb_client import DICOMfileClient
from common.types import DicomNode, DicomNodeBase, DicomWebNode
from webinterface.query import SimpleDicomClient
# Standard python includes
from datetime import datetime
import time, random
# Starlette-related includes
from starlette.authentication import requires

# App-specific includes
from common.constants import mercure_defs
from webinterface.common import templates
import common.config as config
from starlette.responses import PlainTextResponse, JSONResponse
from webinterface.common import worker_queue, redis
from rq import Connection 
from rq.job import Dependency, JobStatus
from rq import get_current_job
from rq.job import Job
from .common import router
from dicomweb_client.api import DICOMwebClient

logger = config.get_logger()




def query_dummy(job_id, job_kwargs):
    """
    Dummy function to simulate a long-running task.
    """
    total_time = 2  # Total time for the job in seconds (1 minute)
    update_interval = 0.25  # Interval between updates in seconds
    remaining = total_time // update_interval
    completed = 0
    start_time = time.monotonic()

    while (time.monotonic() - start_time) < total_time:
        time.sleep(update_interval)  # Sleep for the interval duration
        out_file = (Path(job_kwargs['path']) / f"dummy{completed}_{job_id}.dcm")
        if out_file.exists():
            raise Exception(f"{out_file} exists already")
        out_file.touch()
        remaining -= 1
        completed += 1

        yield completed, remaining, f"{completed} / {remaining + completed}"


@dataclass
class ClassBasedRQJob():
    parent: Optional[str] = None
    type: str = "unknown"
    _job: Optional[Job] = None
    def create(self, rq_options={}, **kwargs) -> Job:
        fields = dataclasses.fields(self)
        meta = {field.name: getattr(self, field.name) for field in fields}
        return Job.create(self._execute, kwargs=kwargs, meta=meta, **rq_options)

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
        return result

    def execute(self):
        pass
    
    @staticmethod
    def move_to_destination(path, destination, job_id) -> None:
        if destination is None:
            config.read_config()
            for p in Path(path).glob("**/*"):
                if p.is_file():
                    shutil.move(str(p), config.mercure.incoming_folder) # Move the file to incoming folder
            # tree(config.mercure.incoming_folder)
            shutil.rmtree(path)
        else:
            dest_folder: Path = Path(destination) / job_id
            dest_folder.mkdir(exist_ok=True)
            logger.info(f"moving {path} to {dest_folder}")
            shutil.move(path, dest_folder)
            # tree(dest_folder)
            logger.info(f"moved")


@dataclass
class CheckAccessionsDicomWebJob(ClassBasedRQJob):
    type: str = "check_accessions_dicomweb"

    def execute(self, *, accessions, node: DicomWebNode, queue=worker_queue): 
        client = (DICOMfileClient(url=node.base_url, in_memory=True) if node.base_url.startswith("file://") 
                  else DICOMwebClient(node.base_url))
        assert isinstance(client, (DICOMwebClient, DICOMfileClient))
        for accession in accessions:
            try:
                response = client.search_for_series(search_filters={'AccessionNumber': accession})
                if not response:
                    raise ValueError("No series found with accession number {}".format(accession))
            except Exception as e:
                job = self._job
                job_parent = queue.fetch_job(job.meta.get('parent'))
                job_parent.meta['failed_reason'] = f"Accession {accession} not found on node"
                job_parent.save_meta()
                queue._enqueue_job(job_parent,at_front=True)
                raise
        return "Complete"

@dataclass 
class CheckAccessionsJob(ClassBasedRQJob):
    type: str = "check_accessions"

    def execute(self, *, accessions, node, queue=worker_queue):
        """
        Check if the given accessions exist on the node using a DICOM query.
        """
        c = SimpleDicomClient(node.ip, node.port, node.aet_target, None)
        assert self.parent is not None
        try:
            for accession in accessions:
                result = c.findscu(accession)
                logger.info(result)
        except:
            job_parent = queue.fetch_job(self.parent)
            job_parent.meta['failed_reason'] = f"Accession {accession} not found on node"
            queue._enqueue_job(job_parent,at_front=True)
            raise

@dataclass
class GetAccessionJob(ClassBasedRQJob):
    type: str = "get_accession"
    paused: bool = False
    offpeak: bool = False

    @classmethod
    def get_accession(cls, job_id, accession, node, path) -> Generator[Tuple[int,int,str], None, str]:
        config.read_config()
        c = SimpleDicomClient(node.ip, node.port, node.aet_target, path)
        for identifier in c.getscu(accession):
            completed, remaining = identifier.NumberOfCompletedSuboperations, identifier.NumberOfRemainingSuboperations, 
            progress = f"{ completed } / { completed + remaining }" 
            yield completed, remaining, progress
        return "Complete"

    def execute(self, *,accession, node, path, queue=worker_queue):
        print(f"Getting {accession}")
        job = self._job
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            job_parent = None
            if parent_id := self.parent:
                job_parent = queue.fetch_job(parent_id)

            if job_parent:
                job_parent.meta['started'] = job_parent.meta.get('started',0) + 1
                job_parent.save_meta()

            job.meta['started'] = 1
            job.meta['progress'] = "0 / Unknown"
            job.save_meta() # type: ignore
            for completed, remaining, progress in self.get_accession(job.id, accession, node, path):
                job.meta['remaining'] = remaining
                job.meta['completed'] = completed
                job.meta['progress'] = progress
                job.save_meta() # type: ignore  # Save the updated meta data to the job
                logger.info(progress)
            if job_parent:
                if job_parent.kwargs["move_promptly"]:
                    self.move_to_destination(path, job_parent.kwargs["destination"], job_parent.id)

                job_parent.get_meta() # there is technically a race condition here...
                job_parent.meta['completed'] += 1
                job_parent.meta['progress'] = f"{job_parent.meta['started'] } / {job_parent.meta['completed'] } / {job_parent.meta['total']}"
                job_parent.save_meta()
        except:
            if not job_parent:
                raise
            # Cancel remaining sibling jobs
            logger.info("Cancelling sibling jobs.")
            for subjob_id in job_parent.kwargs.get('subjobs',[]):
                if subjob_id == job.id:
                    continue
                subjob = queue.fetch_job(subjob_id)
                if subjob.get_status() not in ('finished', 'canceled','failed'):
                    subjob.cancel()
            job_parent.get_meta() 
            logger.info("Cancelled sibling jobs.")
            job_parent.meta["failed_reason"] = f"Failed to retrieve {accession}"
            queue._enqueue_job(job_parent,at_front=True) # Force the parent job to run and fail itself
            raise

        return "Job complete"

@dataclass
class GetAccessionDicomWebJob(GetAccessionJob):
    type: str = "get_accession_dicomweb"

    @classmethod
    def get_accession(cls, job_id, accession, node, path) -> Generator[Tuple[int,int,str], None, None]:
        config.read_config()
        assert isinstance(node, DicomWebNode), f"Invalid node type {type(node)}: expected DicomWebNode"
        client = (DICOMfileClient(url=node.base_url, in_memory=True) if node.base_url.startswith("file://") 
                  else DICOMwebClient(node.base_url))
        assert isinstance(client, (DICOMwebClient, DICOMfileClient))
        series = client.search_for_series(search_filters={'AccessionNumber': accession})
        if not series:
            raise ValueError("No series found with accession number {}".format(accession))
        n = 0
        remaining = 0
        for s in series:
            instances = client.retrieve_series(s['0020000D']['Value'][0], s['0020000E']['Value'][0])
            remaining += len(instances)
            for instance in instances:
                sop_instance_uid = instance.get('SOPInstanceUID')
                filename = f"{path}/{sop_instance_uid}.dcm"
                instance.save_as(filename)
                n += 1
                remaining -= 1
                yield (n, remaining, f'{n} / {n + remaining}')

@dataclass
class MainJob(ClassBasedRQJob):
    type: str = "batch" 
    started: int = 0
    completed: int = 0
    total: int = 0
    paused: bool = False 
    offpeak: bool = False

    def execute(self, *, accessions, subjobs, path, destination, move_promptly, queue=worker_queue) -> str:
        job = self._job
        job.get_meta()
        for job_id in job.kwargs.get('subjobs',[]):
            subjob = queue.fetch_job(job_id)
            if (status := subjob.get_status()) != 'finished':
                raise Exception(f"Subjob {subjob.id} is {status}")
            if job.kwargs.get('failed', False):
                raise Exception(f"Failed")

        logger.info(f"Job completing {job.id}")

        if not move_promptly:
            logger.info("Moving files during completion as move_promptly==False")
            for p in Path(path).iterdir():
                if not p.is_dir():
                    continue
                self.move_to_destination(p, destination, job.id)
        logger.info(f"Removing job directory {path}")
        # tree(destination)
        shutil.rmtree(path)

        return "Job complete"


def monitor_job():
    print("monitoring")

class DicomQueryFlow():
    CheckAccessions = CheckAccessionsJob
    GetAccession = GetAccessionJob

class DicomWebQueryFlow():
    CheckAccessions = CheckAccessionsDicomWebJob
    GetAccession = GetAccessionDicomWebJob

class WrappedJob():
    def __init__(self, job: Union[Job,str], queue):
        if isinstance(job, str):
            self.job = queue.fetch_job(job)
        else:
            self.job = job
        assert self.job.meta.get('type') == 'batch', f"Job type must be batch, got {self.job.meta['type']}"
        self.queue = queue

    @classmethod
    def create(cls, accessions, dicom_node: DicomNodeBase, destination_path, offpeak=False, queue=worker_queue) -> 'WrappedJob':
        """
        Create a job to process the given accessions and store them in the specified destination path.
        """
        if isinstance(dicom_node, DicomNode):
            DicomFlow = DicomQueryFlow
        elif isinstance(dicom_node, DicomWebNode):
            DicomFlow = DicomWebQueryFlow

        with Connection(redis):
            jobs: List[Job] = []
            check_job = DicomFlow.CheckAccessions().create(accessions=accessions, node=dicom_node)
            for accession in accessions:
                job = DicomFlow.GetAccession(offpeak=offpeak).create(
                    accession=accession, 
                    node=dicom_node,
                    rq_options=dict(
                        depends_on=cast(List[Union[Dependency, Job]],[check_job]),
                        timeout=30*60,
                        result_ttl=-1
                        )
                    )
                jobs.append(job)
            depends = Dependency(
                jobs=cast(List[Union[Job,str]],jobs),
                allow_failure=True,    # allow_failure defaults to False
            )
            full_job = MainJob(total=len(jobs), offpeak=offpeak).create(
                accessions = accessions,
                subjobs = [j.id for j in jobs],
                destination = destination_path,
                move_promptly = True,
                rq_options = dict(depends_on=depends, timeout=-1, result_ttl=-1)
            )
            check_job.meta["parent"] = full_job.id
            for j in jobs:
                j.meta["parent"] = full_job.id
                j.kwargs["path"] = Path(config.mercure.jobs_folder) / full_job.id / j.kwargs['accession']
                j.kwargs["path"].mkdir(parents=True)

            full_job.kwargs["path"] = Path(config.mercure.jobs_folder) / full_job.id

        queue.enqueue_job(check_job)
        for j in jobs:
            queue.enqueue_job(j)
        queue.enqueue_job(full_job)

        wrapped_job = WrappedJob(full_job, queue=queue)
        if offpeak and not _is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time()):
            wrapped_job.pause()

        return wrapped_job

    def __bool__(self) -> bool:
        return bool(self.job)

    def pause(self) -> None:
        """
        Pause the current job, including all its subjobs.
        """
        for job_id in self.job.kwargs.get('subjobs',[]):
            subjob = self.queue.fetch_job(job_id)
            if subjob and (subjob.is_deferred or subjob.is_queued):
                subjob.meta['paused'] = True
                subjob.save_meta() # type: ignore
                subjob.cancel()
        self.job.get_meta()
        self.job.meta['paused'] = True
        self.job.save_meta() # type: ignore

    def resume(self) -> None:
        """
        Resume a paused job by unpausing all its subjobs
        """
        for subjob_id in self.job.kwargs.get('subjobs',[]):
            subjob = self.job.fetch_job(subjob_id)
            if subjob and subjob.meta.get('paused', None):
                subjob.meta['paused'] = False
                subjob.save_meta() # type: ignore
                self.queue.canceled_job_registry.requeue(subjob_id)
        self.job.get_meta()
        self.job.meta['paused'] = False
        self.job.save_meta() # type: ignore

    def retry(self) -> None:
        """
        Retry a failed job by enqueuing it again
        """
        # job.meta["retries"] = job.meta.get("retries", 0) + 1
        # if job.meta["retries"] > 3:
        #     return False
        logger.info(f"Retrying {self.job}")
        for subjob in self.get_subjobs():
            if (status:=self.job.get_status()) in ("failed", "canceled"):
                logger.info(f"Retrying {subjob}")
                if status == "failed" and (job_path:=Path(subjob.kwargs['path'])).exists():
                    shutil.rmtree(job_path) # Clean up after a failed job
                self.queue.enqueue_job(subjob)
        self.queue.enqueue_job(self.job)

    @classmethod
    def update_all_jobs_offpeak(cls,queue=worker_queue) -> None:
        """
        Resume or pause offpeak jobs based on whether the current time is within offpeak hours.
        """
        config.read_config()
        is_offpeak = _is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time())
        logger.info(f"is_offpeak {is_offpeak}")
        for job in WrappedJob.get_all_jobs(queue=queue):
            job.update_offpeak(is_offpeak)

    def update_offpeak(self, is_offpeak) -> None:
        if not self.meta.get("offpeak"):
            return
        if self.get_status() not in ("waiting", "running", "queued", "deferred"):
            return

        if is_offpeak:
            # logger.info(f"{job.meta}, {job.get_status()}")
            if self.is_paused:
                logger.info("Resuming")
                self.resume()
        else:
            if not self.is_paused:
                logger.info("Pausing")
                self.pause()

    def get_subjobs(self) -> Generator[Job, None, None]:
        return (self.queue.fetch_job(job) for job in self.job.kwargs.get('subjobs', []) if job)

    def get_status(self) -> JobStatus:
        return cast(JobStatus,self.job.get_status())

    def get_meta(self) -> Any:
        return cast(dict,self.job.get_meta())
        
    @property
    def meta(self) -> typing.Dict:
        return cast(dict, self.job.meta)
    
    @property
    def is_failed(self) -> bool:
        return cast(bool,self.job.is_failed)

    @property
    def is_finished(self) -> bool:
        return cast(bool,self.job.is_finished)
    
    @property
    def is_paused(self) -> bool:
        return cast(bool,self.meta.get("paused",False))

    @property
    def id(self) -> str:
        return cast(str,self.job.id)

    @property
    def kwargs(self) -> typing.Dict:
        return cast(dict,self.job.kwargs)
    
    @property
    def result(self) -> Any:
        return self.job.result
    
    @property
    def created_at(self) -> datetime:
        return cast(datetime,self.job.created_at)
    
    @property
    def enqueued_at(self) -> datetime:
        return cast(datetime,self.job.enqueued_at)

    @classmethod
    def get_all_jobs(cls, type:str="batch", queue=worker_queue) -> Generator['WrappedJob', None, None]:
        """
        Get all jobs of a given type from the queue
        """
        registries = [
            queue.started_job_registry,  # Returns StartedJobRegistry
            queue.deferred_job_registry,   # Returns DeferredJobRegistry
            queue.finished_job_registry,  # Returns FinishedJobRegistry
            queue.failed_job_registry,  # Returns FailedJobRegistry 
            queue.scheduled_job_registry,  # Returns ScheduledJobRegistry
            queue.canceled_job_registry,   # Returns CanceledJobRegistry
        ]
        job_ids = set()
        for registry in registries:
            for j_id in registry.get_job_ids():
                job_ids.add(j_id)
        for j_id in queue.job_ids:
            job_ids.add(j_id)
        jobs = (queue.fetch_job(j_id) for j_id in job_ids)

        return (WrappedJob(j,queue) for j in jobs if j.get_meta().get("type") == type)

def _is_offpeak(offpeak_start: str, offpeak_end: str, current_time) -> bool:
    try:
        start_time = datetime.strptime(offpeak_start, "%H:%M").time()
        end_time = datetime.strptime(offpeak_end, "%H:%M").time()
    except Exception as e:
        logger.error(f"Unable to parse offpeak time: {offpeak_start}, {offpeak_end}", None)  # handle_error
        return True

    if start_time < end_time:
        return bool(current_time >= start_time and current_time <= end_time)
    # End time is after midnight
    return bool(current_time >= start_time or current_time <= end_time)

 
@router.post("/query/retry_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_retry_job(request):
    job = WrappedJob(request.query_params['id'], queue=worker_queue)
    job.retry()
    return JSONResponse({})

@router.post("/query/pause_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_pause_job(request):
    job = WrappedJob(request.query_params['id'], queue=worker_queue)
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    job.pause()
    return JSONResponse({'status': 'success'}, status_code=200)

@router.post("/query/resume_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_resume_job(request):
    job = WrappedJob(request.query_params['id'], queue=worker_queue)
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    
    job.resume()
    return JSONResponse({'status': 'success'}, status_code=200)

@router.get("/query/job_info")
@requires(["authenticated", "admin"], redirect="login")
async def get_job_info(request):
    job_id = request.query_params['id']
    job = WrappedJob(job_id, queue=worker_queue)
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    
    subjob_info:List[Dict[str,Any]] = []
    for subjob in job.get_subjobs():
        if not subjob:
            continue
        info = {
                'id': subjob.get_id(),
                'ended_at': subjob.ended_at.isoformat().split('.')[0] if subjob.ended_at else "", 
                'created_at_dt':subjob.created_at,
                'accession': subjob.kwargs['accession'],
                'progress': subjob.meta.get('progress'),
                'paused': subjob.meta.get('paused',False),
                'status': subjob.get_status()
            }
        if info['status'] == 'canceled' and info['paused']:
            info['status'] = 'paused'
        subjob_info.append(info)
    subjob_info = sorted(subjob_info, key=lambda x:x['created_at_dt'])
    return templates.TemplateResponse("dashboards/query_job_fragment.html", {"request":request,"job":job,"subjob_info":subjob_info})



@router.post("/query")
@requires(["authenticated", "admin"], redirect="login")
async def query_post_batch(request):
    """
    Starts a new query job for the given accession number and DICOM node.
    """
    form = await request.form()
    for n in config.mercure.dicom_retrieve.dicom_nodes:
        if n.name == form.get("dicom_node"):
            node = n
            break
    destination = form.get("destination")
    dest_path = None
    for d in config.mercure.dicom_retrieve.destination_folders:
        if d.name == destination:
            dest_path = d.path
            break

    # random_accessions = ["".join(random.choices([str(i) for i in range(10)], k=10)) for _ in range(3)]
    offpeak = 'offpeak' in form
    WrappedJob.create(form.get("accession").split(","), node, dest_path, offpeak=offpeak)
    # worker_scheduler.schedule(scheduled_time=datetime.utcnow(), func=monitor_job, interval=10, repeat=10, result_ttl=-1)
    return PlainTextResponse()
 
@router.post("/query_single")
@requires(["authenticated", "admin"], redirect="login")
async def query_post(request):
    """
    Starts a new query job for the given accession number and DICOM node.
    """
    form = await request.form()
    for n in config.mercure.dicom_retrieve.dicom_nodes:
        if n.name == form.get("dicom_node"):
            node = n
            break
    
    worker_queue.enqueue_call(QueryJob.get_accession_job, kwargs=dict(accession=form.get("accession"), node=node), timeout=30*60, result_ttl=-1, meta=dict(type="get_accession_single"))
    return PlainTextResponse()


@router.get("/query/jobs")
@requires(["authenticated", "admin"], redirect="login")
async def query_jobs(request):
    """
    Returns a list of all query jobs. 
    """
    job_info = []
    for job in WrappedJob.get_all_jobs():
        job_dict = dict(id=job.id, 
                                status=job.get_status(), 
                                parameters=dict(accession=job.kwargs.get('accession','')), 
                                created_at=1000*datetime.timestamp(job.created_at) if job.created_at else "",
                                enqueued_at=1000*datetime.timestamp(job.enqueued_at) if job.enqueued_at else "", 
                                result=job.result if job.get_status() != "failed" else job.meta.get("failed_reason",""), 
                                meta=job.meta,
                                progress="")
        # if job.meta.get('completed') and job.meta.get('remaining'):
        #     job_dict["progress"] = f"{job.meta.get('completed')} / {job.meta.get('completed') + job.meta.get('remaining')}"
        # if job.meta.get('type',None) == "batch":
        n_started = job.meta.get('started',0)
        n_completed = job.meta.get('completed',0)
        n_total = job.meta.get('total',0)

        if job_dict["status"] == "finished":
            job_dict["progress"] = f"{n_total} / {n_total}"
        elif job_dict["status"] in ("deferred","started", "paused", "canceled"):
            job_dict["progress"] = f"{n_completed} / {n_total}"
        
        # if job_dict["status"] == "canceled" and 
        if job_dict["meta"].get('paused', False) and job_dict["status"] not in ("finished", "failed"):
            if n_started < n_completed: # TODO: this does not work
                job_dict["status"] = "pausing"
            else:
                job_dict["status"] = "paused"

        if job_dict["status"] in ("deferred", "started"):
            if n_started == 0:
                job_dict["status"] = "waiting"
            elif n_completed < n_total:
                job_dict["status"] = "running" 
            elif n_completed == n_total:
                job_dict["status"] = "finishing" 

        job_info.append(job_dict)
    return JSONResponse(dict(data=job_info))
    # return PlainTextResponse(",".join([str(j) for j in all_jobs]))

@router.get("/query")
@requires(["authenticated", "admin"], redirect="login")
async def query(request):
    template = "dashboards/query.html"
    context = {
        "request": request,
        "destination_folders": config.mercure.dicom_retrieve.destination_folders,
        "dicom_nodes": config.mercure.dicom_retrieve.dicom_nodes,
        "page": "query",
    }
    return templates.TemplateResponse(template, context)