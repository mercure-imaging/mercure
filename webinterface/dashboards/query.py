
from pathlib import Path
import shutil
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
from rq.job import Dependency
from rq import get_current_job
from rq.job import Job
from .common import router
logger = config.get_logger()



def get_accession_job(job_id, job_kwargs):
    accession, node, path = job_kwargs["accession"], job_kwargs["node"], job_kwargs["path"]
    config.read_config()
    c = SimpleDicomClient(node.ip, node.port, node.aet_target, path)
    # job = get_current_job()
    # job.meta["started"] = 1
    # job.save_meta()
    for identifier in c.getscu(accession):
        completed, remaining = identifier.NumberOfCompletedSuboperations, identifier.NumberOfRemainingSuboperations, 
        progress = f"{ completed } / { completed + remaining }"
        yield completed, remaining, progress
    return "Complete"

def check_accessions_exist(*, accessions, node):
    c = SimpleDicomClient(node.ip, node.port, node.aet_target, None)
    try:
        for accession in accessions:
            result = c.findscu(accession)
            logger.info(result)
    except:
        job = get_current_job()
        job_parent = worker_queue.fetch_job(job.meta.get('parent'))
        job_parent.meta['failed_reason'] = f"Accession {accession} not found on node"
        worker_queue._enqueue_job(job_parent,at_front=True)
        raise
def query_dummy(job_id, job_kwargs):
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

class QueryJob():

    @classmethod
    def get_accessions(cls, *,accession, node, path, perform_func=query_dummy):
        print(f"Getting {accession}")
        job = get_current_job()
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            job_parent = None
            if parent_id := job.meta.get('parent'):
                job_parent = worker_queue.fetch_job(parent_id)

            if job_parent:
                job_parent.meta['started'] = job_parent.meta.get('started',0) + 1
                job_parent.save_meta()

            job.meta['started'] = 1
            job.meta['progress'] = "0 / Unknown"
            job.save_meta()
            for completed, remaining, progress in perform_func(job.id, job.kwargs):
                job.meta['remaining'] = remaining
                job.meta['completed'] = completed
                job.meta['progress'] = progress
                job.save_meta()  # Save the updated meta data to the job
                logger.info(progress)
            if job_parent.kwargs["move_promptly"]:
                move_to_destination(path, job_parent.kwargs["destination"], job_parent.id)
            if job_parent:
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
                subjob = worker_queue.fetch_job(subjob_id)
                if subjob.get_status() not in ('finished', 'canceled','failed'):
                    subjob.cancel()
            job_parent.get_meta() 
            logger.info("Cancelled sibling jobs.")
            job_parent.meta["failed_reason"] = f"Failed to retrieve {accession}"
            worker_queue._enqueue_job(job_parent,at_front=True) # Force the parent job to run and fail itself
            raise

        return "Job complete"

def move_to_destination(path, destination, job_id):
    if destination is None:
        config.read_config()
        for p in Path(path).glob("**/*"):
            if p.is_file():
                shutil.move(p, config.mercure.incoming_folder)
        shutil.rmtree(path)
    else:
        dest_folder: Path = Path(destination) / job_id
        dest_folder.mkdir(exist_ok=True)
        logger.info(f"moving {path} to {dest_folder}")
        shutil.move(path, dest_folder)

def batch_job(*, accessions, subjobs, path, destination, move_promptly):
    job = get_current_job()
    job.get_meta()
    for job_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(job_id)
        if (status := subjob.get_status()) != 'finished':
            raise Exception(f"Subjob {subjob.id} is {status}")
        if job.kwargs.get('failed', False):
            raise Exception(f"Failed")

    logger.info(f"Job completing {job.id}")

    if not move_promptly:
        for p in Path(path).iterdir():
            if not p.is_dir():
                continue
            move_to_destination(p, destination, job.id)
    shutil.rmtree(path)

    return "Job complete"



def monitor_job():
    print("monitoring")

def pause_job(job: Job):
    for job_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(job_id)
        if subjob and (subjob.is_deferred or subjob.is_queued):
            subjob.meta['paused'] = True
            subjob.save_meta()
            subjob.cancel()
    job.get_meta()
    job.meta['paused'] = True
    job.save_meta()

def resume_job(job: Job):
    for subjob_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(subjob_id)
        if subjob and subjob.meta.get('paused', None):
            subjob.meta['paused'] = False
            subjob.save_meta()
            worker_queue.canceled_job_registry.requeue(subjob_id)
    job.get_meta()
    job.meta['paused'] = False
    job.save_meta()

def create_job(accessions, dicom_node, destination_path, offpeak=False) -> Job:
    with Connection(redis):
        jobs = []
        check_job = Job.create(check_accessions_exist, kwargs=dict(accessions=accessions,node=dicom_node), meta=dict(parent=None))

        for accession in accessions:
            job = Job.create(QueryJob.get_accessions, kwargs=dict(perform_func=get_accession_job, accession=accession, node=dicom_node), timeout='30m', result_ttl=-1, meta=dict(type="get_accession_batch",parent=None, paused=False, offpeak=offpeak),depends_on=[check_job])
            jobs.append(job)
        depends = Dependency(
            jobs=jobs,
            allow_failure=True,    # allow_failure defaults to False
        )
        full_job = Job.create(batch_job, kwargs=dict(accessions=accessions, subjobs=[j.id for j in jobs], destination=destination_path, move_promptly=True), timeout=-1, result_ttl=-1, meta=dict(type="batch", started=0, paused=False,completed=0, total=len(jobs), offpeak=offpeak), depends_on=depends)
        check_job.meta["parent"] = full_job.id
        for j in jobs:
            j.meta["parent"] = full_job.id
            j.kwargs["path"] = f"/opt/mercure/data/query/job_dirs/{full_job.id}/{j.kwargs['accession']}"
        full_job.kwargs["path"] = Path(f"/opt/mercure/data/query/job_dirs/{full_job.id}")
        full_job.kwargs["path"].mkdir(parents=True)

    worker_queue.enqueue_job(check_job)
    for j in jobs:
        worker_queue.enqueue_job(j)
    worker_queue.enqueue_job(full_job)

    if offpeak and not _is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time()):
        pause_job(full_job)

    return full_job

def retry_job(job):
    # job.meta["retries"] = job.meta.get("retries", 0) + 1
    # if job.meta["retries"] > 3:
    #     return False
    logger.info(f"Retrying {job}")
    for subjob in get_subjobs(job):
        if (status:=job.get_status()) in ("failed", "canceled"):
            logger.info(f"Retrying {subjob}")
            if status == "failed" and (job_path:=Path(subjob.kwargs['path'])).exists():
                shutil.rmtree(job_path) # Clean up after a failed job
            worker_queue.enqueue_job(subjob)
    worker_queue.enqueue_job(job)
def get_subjobs(job):
    return (worker_queue.fetch_job(job) for job in job.kwargs.get('subjobs', []))

def get_all_jobs(type):
    registries = [
        worker_queue.started_job_registry,  # Returns StartedJobRegistry
        worker_queue.deferred_job_registry,   # Returns DeferredJobRegistry
        worker_queue.finished_job_registry,  # Returns FinishedJobRegistry
        worker_queue.failed_job_registry,  # Returns FailedJobRegistry 
        worker_queue.scheduled_job_registry,  # Returns ScheduledJobRegistry
        worker_queue.canceled_job_registry,   # Returns CanceledJobRegistry
    ]
    job_ids = set()
    for registry in registries:
        for j_id in registry.get_job_ids():
            job_ids.add(j_id)
    for j_id in worker_queue.job_ids:
        job_ids.add(j_id)
    jobs = (worker_queue.fetch_job(j_id) for j_id in job_ids)

    return (j for j in jobs if j.get_meta().get("type") == type)

def _is_offpeak(offpeak_start: str, offpeak_end: str, current_time) -> bool:
    try:
        start_time = datetime.strptime(offpeak_start, "%H:%M").time()
        end_time = datetime.strptime(offpeak_end, "%H:%M").time()
    except Exception as e:
        logger.error(f"Unable to parse offpeak time: {offpeak_start}, {offpeak_end}", None)  # handle_error
        return True

    if start_time < end_time:
        return current_time >= start_time and current_time <= end_time
    # End time is after midnight
    return current_time >= start_time or current_time <= end_time

def update_jobs_offpeak():
    config.read_config()
    is_offpeak = _is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time())
    logger.info(f"is_offpeak {is_offpeak}")
    for job in get_all_jobs("batch"):
        if not job.meta.get("offpeak"):
            continue
        if job.get_status() not in ("waiting", "running", "queued", "deferred"):
            continue

        if is_offpeak:
            logger.info(f"{job.meta}, {job.get_status()}")
            if job.meta.get("paused", False):
                logger.info("Resuming")
                resume_job(job)
        else:
            if not job.meta.get("paused", False):
                logger.info("Pausing")
                pause_job(job)

@router.post("/query/retry_job")
@requires(["authenticated", "admin"], redirect="login")
async def test_offpeak(request):
    job = worker_queue.fetch_job(request.query_params['id'])
    retry_job(job)
    return JSONResponse({})
@router.post("/query/pause_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_pause_job(request):
    job = worker_queue.fetch_job(request.query_params['id'])
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    pause_job(job)
    return JSONResponse({'status': 'success'}, status_code=200)

@router.post("/query/resume_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_resume_job(request):
    job = worker_queue.fetch_job(request.query_params['id'])
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    
    resume_job(job)
    return JSONResponse({'status': 'success'}, status_code=200)

@router.get("/query/job_info")
@requires(["authenticated", "admin"], redirect="login")
async def get_job_info(request):
    job_id = request.query_params['id']
    job = worker_queue.fetch_job(job_id)
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    
    subjob_info = []
    subjobs = (worker_queue.fetch_job(job) for job in job.kwargs.get('subjobs', []))
    for subjob in subjobs:
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
    create_job(form.get("accession").split(","), node, dest_path, offpeak=offpeak)
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
    
    worker_queue.enqueue_call(query_job, kwargs=dict(accession=form.get("accession"), node=node), timeout='30m', result_ttl=-1, meta=dict(type="get_accession_single"))
    return PlainTextResponse()


@router.get("/query/jobs")
@requires(["authenticated", "admin"], redirect="login")
async def query_jobs(request):
    job_info = []
    for job in get_all_jobs("batch"):
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