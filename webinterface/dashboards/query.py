
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
from rq import get_current_job
from rq.job import Job
from .common import router
logger = config.get_logger()

def query_job(*,accession, node):
    config.read_config()
    c = SimpleDicomClient(node.ip, node.port, node.aet_target, config.mercure.incoming_folder)
    job = get_current_job()
    job.meta["started"] = 1
    job.save_meta()
    for identifier in c.getscu(accession):
        job.meta['failed'] = identifier.NumberOfFailedSuboperations
        job.meta['remaining'] = identifier.NumberOfRemainingSuboperations
        job.meta['completed'] = identifier.NumberOfCompletedSuboperations
        if not job.meta.get('total', False):
            job.meta['total'] = identifier.NumberOfCompletedSuboperations + identifier.NumberOfRemainingSuboperations
        job.meta["started"] += 1
        job.save_meta()
    return "Complete"

def dummy_job(*,accession, node, path):
    Path(path).mkdir(parents=True, exist_ok=True)
    total_time = 3  # Total time for the job in seconds (1 minute)
    update_interval = 1  # Interval between updates in seconds

    start_time = time.monotonic()
    job = get_current_job()
    if job.meta.get('parent'):
        job_parent = worker_queue.fetch_job(job.meta['parent'])
    else:
        job_parent = None
    # failed = 0
    remaining = total_time // update_interval
    completed = 0
    print(accession)
    if job_parent:
        job_parent.meta['started'] = job_parent.meta.get('started',0) + 1
        job_parent.save_meta()

    job.meta['started'] = 1
    job.meta['total'] = remaining
    job.meta['progress'] = f"0 / {job.meta['total']}"
    job.save_meta()
    while (time.monotonic() - start_time) < total_time:
        time.sleep(update_interval)  # Sleep for the interval duration
        (Path(path) / f"dummy{completed}_{job.id}.dcm").touch()
        remaining -= 1
        completed += 1

        # job.meta['failed'] = failed
        job.meta['remaining'] = remaining
        job.meta['completed'] = completed
        job.meta['progress'] = f"{completed} / {job.meta['total']}"
        print(job.meta['progress'])
        job.save_meta()  # Save the updated meta data to the job
    
    if job_parent:
        job_parent.meta['completed'] += 1
        job_parent.meta['progress'] = f"{job_parent.meta['completed'] } / {job_parent.meta['total']}"

        job_parent.save_meta()
    return "Job complete"

def batch_job(*, accessions, subjobs, path):
    for p in Path(path).glob("**/*.dcm"):
        shutil.move(p, "/opt/mercure/data/incoming")
    shutil.rmtree(path)
    return "Batch complete"

def monitor_job():
    print("monitoring")

@router.get("/query/job_info")
@requires(["authenticated", "admin"], redirect="login")
async def get_job_info(request):
    job_id = request.query_params['id']
    job = worker_queue.fetch_job(job_id)
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    
    subjob_info = []
    for job_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(job_id)
        if subjob:
            subjob_info.append({'id': subjob.get_id(),
                                'ended_at': subjob.ended_at.isoformat().split('.')[0] if subjob.ended_at else "", 
                                'created_at_dt':subjob.created_at,
                                'accession': subjob.kwargs['accession'],
                                'progress': subjob.meta.get('progress'),
                                'status': subjob.get_status()})
    subjob_info = sorted(subjob_info, key=lambda x:x['created_at_dt'])
    return templates.TemplateResponse("dashboards/query_job_fragment.html", {"request":request,"subjob_info":subjob_info})

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
    random_accessions = ["".join(random.choices([str(i) for i in range(10)], k=10)) for _ in range(5)]
    jobs = []
    with Connection(redis):
        for accession in random_accessions:
            job = Job.create(dummy_job, kwargs=dict(accession=accession, node=node), timeout='30m', result_ttl=-1, meta=dict(type="get_accession_batch",parent=None))
            jobs.append(job)
        full_job = Job.create(batch_job, kwargs=dict(accessions=random_accessions, subjobs=[j.id for j in jobs]), timeout=-1, result_ttl=-1, meta=dict(type="batch", started=0, completed=0, total=len(jobs)), depends_on=[j.id for j in jobs])
        for j in jobs:
            j.meta["parent"] = full_job.id
            j.kwargs["path"] = f"/opt/mercure/data/query/job_dirs/{full_job.id}/{j.kwargs['accession']}"
        full_job.kwargs["path"] = Path(f"/opt/mercure/data/query/job_dirs/{full_job.id}")


    for j in jobs:
        worker_queue.enqueue_job(j)
    worker_queue.enqueue_job(full_job)

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
    registries = [
        worker_queue.started_job_registry,  # Returns StartedJobRegistry
        worker_queue.deferred_job_registry,   # Returns DeferredJobRegistry
        worker_queue.finished_job_registry,  # Returns FinishedJobRegistry
        worker_queue.failed_job_registry,  # Returns FailedJobRegistry 
        worker_queue.scheduled_job_registry,  # Returns ScheduledJobRegistry
    ]
    job_info = []
    for r in registries:
        for j_id in r.get_job_ids():
            job = worker_queue.fetch_job(j_id)
            if job.meta.get('type') != 'batch':
                continue
            job_dict = dict(id=j_id, 
                                 status=job.get_status(), 
                                 parameters=dict(accession=job.kwargs.get('accession','')), 
                                 created_at=1000*datetime.timestamp(job.created_at) if job.created_at else "",
                                 enqueued_at=1000*datetime.timestamp(job.enqueued_at) if job.enqueued_at else "", 
                                 result=job.result, 
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
            elif job_dict["status"] in ("deferred","started"):
                job_dict["progress"] = f"{n_completed} / {n_total}"
                if 0 < n_started < n_total:
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
        
        "dicom_nodes": config.mercure.dicom_retrieve.dicom_nodes,
        "page": "query",
    }
    return templates.TemplateResponse(template, context)