
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from common.types import DicomTarget, DicomWebTarget, FolderTarget
from dispatch.target_types.registry import get_handler
# Standard python includes
from datetime import datetime
# Starlette-related includes
from starlette.authentication import requires

# App-specific includes
from webinterface.common import templates
import common.config as config
from starlette.responses import PlainTextResponse, JSONResponse
from webinterface.common import redis
from rq.job import Job
from rq import Connection

from .common import router

logger = config.get_logger()

from .query.jobs import CheckAccessionsJob, WrappedJob
 
@router.post("/query/retry_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_retry_job(request):
    job = WrappedJob(request.query_params['id'])
    job.retry()
    return JSONResponse({})

@router.post("/query/pause_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_pause_job(request):
    job = WrappedJob(request.query_params['id'])
    if not job:
        return JSONResponse({'error': 'Job not found'}, status_code=404)
    if job.is_finished or job.is_failed:
        return JSONResponse({'error': 'Job is already finished'}, status_code=400)
    job.pause()
    return JSONResponse({'status': 'success'}, status_code=200)

@router.post("/query/resume_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_resume_job(request):
    job = WrappedJob(request.query_params['id'])
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
    job = WrappedJob(job_id)
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

    node = config.mercure.targets.get(form.get("dicom_node"))
    if not isinstance(node, (DicomWebTarget, DicomTarget)):
        return JSONResponse({"error": f"Invalid DICOM node"}, status_code=400)

    destination = config.mercure.targets.get(form.get("destination"))
    if destination and isinstance(destination, FolderTarget):
        dest_path = destination.folder
    else:
        return JSONResponse({"error": "Invalid destination"}, status_code=400)
    # random_accessions = ["".join(random.choices([str(i) for i in range(10)], k=10)) for _ in range(3)]
    offpeak = 'offpeak' in form


    search_filters = {}
    if search_filter:= form.get("series_description"):
        search_filters["SeriesDescription"] = [x.strip() for x in search_filter.split(",")]
    if search_filter:= form.get("study_description"):
        search_filters["StudyDescription"] =  [x.strip() for x in search_filter.split(",")]

    WrappedJob.create(form.get("accession").split(","), search_filters, node, dest_path, offpeak=offpeak)
    # worker_scheduler.schedule(scheduled_time=datetime.utcnow(), func=monitor_job, interval=10, repeat=10, result_ttl=-1)
    return PlainTextResponse()
 
# @router.post("/query_single")
# @requires(["authenticated", "admin"], redirect="login")
# async def query_post(request):
#     """
#     Starts a new query job for the given accession number and DICOM node.
#     """
#     form = await request.form()
#     for n in config.mercure.dicom_retrieve.dicom_nodes:
#         if n.name == form.get("dicom_node"):
#             node = n
#             break
    
#     worker_queue.enqueue_call(QueryJob.get_accession_job, kwargs=dict(accession=form.get("accession"), node=node), timeout=30*60, result_ttl=-1, meta=dict(type="get_accession_single"))
#     return PlainTextResponse()


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
    dicom_nodes = [name for name,node in config.mercure.targets.items() if type(node) in (DicomTarget, DicomWebTarget) and node.direction in ("pull", "both")]
    destination_folders = [name for name,node in config.mercure.targets.items() if type(node) == FolderTarget]
    context = {
        "request": request,
        "destination_folders": destination_folders,
        "dicom_nodes": dicom_nodes,
        "page": "query",
    }
    return templates.TemplateResponse(template, context)

@router.post("/query/check_accessions")
@requires(["authenticated", "admin"], redirect="login")
async def check_accessions(request):
    form = await request.form()
    job_id = form.get("job_id")

    if job_id:
        # Retrieve results for an existing job
        job = Job.fetch(job_id, redis)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        elif job.is_failed:
            job.get_meta()
            logger.warning(job.meta)
            if failed_reason:=job.meta.get("failed_reason"):
                return JSONResponse({"status": "failed", "info": failed_reason})
            else:
                return JSONResponse({"status": "failed", "info": "Unknown error"})
        elif job.is_finished:
            result_data = []
            for d in job.result:
                result_data.append( {x:d.get(x) for x in ["AccessionNumber", "PatientID", "StudyInstanceUID", "SeriesInstanceUID", "StudyDescription", "SeriesDescription", "NumberOfSeriesRelatedInstances"]} )
            return JSONResponse({"status": "completed", "result": result_data})
        

        return JSONResponse({"status": "pending", "job_id": job.id})

    node_name = form.get("dicom_node")
    accessions = form.get("accessions", "").split(",")
    
    series_descriptions = form.get("series_descriptions")
    study_descriptions = form.get("study_descriptions")

    search_filters = {}
    if search_filter:= form.get("series_description"):
        search_filters["SeriesDescription"] = [x.strip() for x in search_filter.split(",")]
    if search_filter:= form.get("study_description"):
        search_filters["StudyDescription"] =  [x.strip() for x in search_filter.split(",")]

    node = config.mercure.targets.get(node_name)
    if not isinstance(node, (DicomWebTarget, DicomTarget)):
        return JSONResponse({"error": f"Invalid DICOM node"}, status_code=400)
    
    with Connection(redis):
        job = CheckAccessionsJob().create(accessions=accessions, node=node, search_filters=search_filters)
        CheckAccessionsJob.queue().enqueue_job(job)
    return JSONResponse({"status": "pending", "job_id": job.id})