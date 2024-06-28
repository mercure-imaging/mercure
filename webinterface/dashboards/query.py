
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
    total_time = 10  # Total time for the job in seconds (1 minute)
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
        out_file = (Path(path) / f"dummy{completed}_{job.id}.dcm")
        if out_file.exists():
            raise Exception(f"{out_file} exists already")
        out_file.touch()
        remaining -= 1
        completed += 1

        # job.meta['failed'] = failed
        job.meta['remaining'] = remaining
        job.meta['completed'] = completed
        job.meta['progress'] = f"{completed} / {job.meta['total']}"
        print(job.meta['progress'])
        job.save_meta()  # Save the updated meta data to the job
    
    if job_parent:
        job_parent.get_meta() # there is technically a race condition here...
        job_parent.meta['completed'] += 1
        job_parent.meta['progress'] = f"{job_parent.meta['started'] } / {job_parent.meta['completed'] } / {job_parent.meta['total']}"

        job_parent.save_meta()
    return "Job complete"

def batch_job(*, accessions, subjobs, path, destination):
    job = get_current_job()
    job.save_meta()
    logger.info(f"Job completing {job.id}")
    logger.info(path)
    if destination is None:
        for p in Path(path).glob("**/*"):
            if p.is_file():
                shutil.move(p, config.mercure.incoming_folder)
    else:
        dest_folder: Path = Path(destination) / job.id
        dest_folder.mkdir()
        for p in Path(path).iterdir():
            if p.is_dir():
                logger.info(f"moving {p} to {dest_folder}")
                shutil.move(p, dest_folder)

    shutil.rmtree(path)
    return "Job complete"



def monitor_job():
    print("monitoring")

@router.post("/query/pause_job")
@requires(["authenticated", "admin"], redirect="login")
async def pause_job(request):
    job = worker_queue.fetch_job(request.query_params['id'])
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)

    for job_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(job_id)
        if subjob and (subjob.is_deferred or subjob.is_queued):
            subjob.meta['paused'] = True
            subjob.save_meta()
            subjob.cancel()
    job.meta['paused'] = True
    job.save_meta()
    return JSONResponse({'status': 'success'}, status_code=200)

@router.post("/query/resume_job")
@requires(["authenticated", "admin"], redirect="login")
async def resume_job(request):
    job = worker_queue.fetch_job(request.query_params['id'])
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    # if not job.meta.get('paused', False):
    #     return JSONResponse({'error': 'Job is not paused'}, status_code=400)

    for subjob_id in job.kwargs.get('subjobs',[]):
        subjob = worker_queue.fetch_job(subjob_id)
        if subjob and subjob.meta.get('paused', None):
            subjob.meta['paused'] = False
            subjob.save_meta()
            worker_queue.canceled_job_registry.requeue(subjob_id)
            # worker_queue.canceled_job_registry.remove(subjob_id)
    job.get_meta()
    job.meta['paused'] = False
    job.save_meta()
    # worker_queue.canceled_job_registry.requeue(job.id)
    # worker_queue.canceled_job_registry.remove(job.id)
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
        info = {'id': subjob.get_id(),
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
    for d in config.mercure.dicom_retrieve.destination_folders:
        if d.name == destination:
            destination_path = d.path
    random_accessions = ["".join(random.choices([str(i) for i in range(10)], k=5)) for _ in range(3)]
    jobs = []
    with Connection(redis):
        for accession in random_accessions:
            job = Job.create(dummy_job, kwargs=dict(accession=accession, node=node), timeout='30m', result_ttl=-1, meta=dict(type="get_accession_batch",parent=None, paused=False))
            jobs.append(job)
        full_job = Job.create(batch_job, kwargs=dict(accessions=random_accessions, subjobs=[j.id for j in jobs], destination=destination_path), timeout=-1, result_ttl=-1, meta=dict(type="batch", started=0, paused=False,completed=0, total=len(jobs)), depends_on=[j.id for j in jobs])
        for j in jobs:
            j.meta["parent"] = full_job.id
            j.kwargs["path"] = f"/opt/mercure/data/query/job_dirs/{full_job.id}/{j.kwargs['accession']}"
        full_job.kwargs["path"] = Path(f"/opt/mercure/data/query/job_dirs/{full_job.id}")
        full_job.kwargs["path"].mkdir(parents=True)

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
        worker_queue.canceled_job_registry,   # Returns CanceledJobRegistry
    ]
    job_info = []
    # logger.info(worker_queue.job_ids)
    # for registry in registries:
    job_ids = set()
    for registry in registries:
        for j_id in registry.get_job_ids():
            job_ids.add(j_id)
    for j_id in worker_queue.job_ids:
        job_ids.add(j_id)

    for j_id in job_ids:
        job = worker_queue.fetch_job(j_id)
        job_meta = job.get_meta()
        if job_meta.get('type') != 'batch':
            continue
        job_dict = dict(id=j_id, 
                                status=job.get_status(), 
                                parameters=dict(accession=job.kwargs.get('accession','')), 
                                created_at=1000*datetime.timestamp(job.created_at) if job.created_at else "",
                                enqueued_at=1000*datetime.timestamp(job.enqueued_at) if job.enqueued_at else "", 
                                result=job.result, 
                                meta=job_meta,
                                progress="")
        # if job.meta.get('completed') and job.meta.get('remaining'):
        #     job_dict["progress"] = f"{job.meta.get('completed')} / {job.meta.get('completed') + job.meta.get('remaining')}"
        # if job.meta.get('type',None) == "batch":
        n_started = job_meta.get('started',0)
        n_completed = job_meta.get('completed',0)
        n_total = job_meta.get('total',0)

        if job_dict["status"] == "finished":
            job_dict["progress"] = f"{n_total} / {n_total}"
        elif job_dict["status"] in ("deferred","started", "paused", "canceled"):
            job_dict["progress"] = f"{n_completed} / {n_total}"
        
        # if job_dict["status"] == "canceled" and 
        if job_dict["meta"].get('paused', False):
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