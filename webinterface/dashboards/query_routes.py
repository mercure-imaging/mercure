
from time import sleep
from typing import Any, Dict, List
from datetime import datetime

# Starlette-related includes
from starlette.authentication import requires
from starlette.responses import JSONResponse

from rq.job import Job
from rq import Connection

# App-specific includes
from webinterface.common import templates
import common.config as config
from common.types import DicomTarget, DicomWebTarget, FolderTarget

from webinterface.common import redis
from .common import router, JSONErrorResponse
from .query.jobs import CheckAccessionsTask, QueryPipeline

logger = config.get_logger()
 
@router.post("/query/retry_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_retry_job(request):
    with Connection(redis):
        job = QueryPipeline(request.query_params['id'])
        
        if not job:
            return JSONErrorResponse(f"Job with id {request.query_params['id']} not found.", status_code=404)
        
        try:
            job.retry()
        except Exception as e:
            logger.exception("Failed to retry job", exc_info=True)
            return JSONErrorResponse("Failed to retry job",status_code=500)
    return JSONResponse({})

@router.post("/query/pause_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_pause_job(request):
    with Connection(redis):
        job = QueryPipeline(request.query_params['id'])

        if not job:
            return JSONErrorResponse('Job not found', status_code=404)
        if job.is_finished or job.is_failed:
            return JSONErrorResponse('Job is already finished', status_code=400)

        try:
            job.pause()
        except Exception as e:
            logger.exception(f"Failed to pause job {request.query_params['id']}")
            return JSONErrorResponse('Failed to pause job', status_code=500)
    return JSONResponse({'status': 'success'}, status_code=200)

@router.post("/query/resume_job")
@requires(["authenticated", "admin"], redirect="login")
async def post_resume_job(request):
    with Connection(redis):
        job = QueryPipeline(request.query_params['id'])
        if not job:
            return JSONErrorResponse('Job not found', status_code=404)
        if job.is_finished or job.is_failed:
            return JSONErrorResponse('Job is already finished', status_code=400)

        try:
            job.resume()
        except Exception as e:
            logger.exception(f"Failed to resume job {request.query_params['id']}")
            return JSONErrorResponse('Failed to resume job', status_code=500)
    return JSONResponse({'status': 'success'}, status_code=200)

@router.get("/query/job_info")
@requires(["authenticated", "admin"], redirect="login")
async def get_job_info(request):
    job_id = request.query_params['id']
    with Connection(redis):
        job = QueryPipeline(job_id)
        if not job:
            return JSONErrorResponse('Job not found', status_code=404)
        
        subjob_info:List[Dict[str,Any]] = []
        for subjob in job.get_subjobs():
            if not subjob:
                continue
            if subjob.meta.get('type') != 'get_accession':
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

    # generate a bunch of dummy data for testing purposes

    return templates.TemplateResponse("dashboards/query_job_fragment.html", {"request":request,"job":job,"subjob_info":subjob_info})



@router.post("/query")
@requires(["authenticated", "admin"], redirect="login")
async def query_post_batch(request):
    """
    Starts a new query job for the given accession number and DICOM node.
    """
    try:
        form = await request.form()
    except Exception as e:
        return JSONErrorResponse("Invalid form data.", status_code=400)
    accession = form.get("accession")
    if not accession:
        return JSONErrorResponse("Accession number is required.", status_code=400)

    node = config.mercure.targets.get(form.get("dicom_node"))
    if not node:
        return JSONErrorResponse(f"No such DICOM node {form.get('dicom_node')}.", status_code=404)
    if not isinstance(node, (DicomWebTarget, DicomTarget)):
        return JSONErrorResponse(f"Invalid DICOM node {form.get('dicom_node')}.", status_code=400)

    destination_name = form.get("destination")
    if not destination_name:
        destination_path = None
    else:
        destination = config.mercure.targets.get(destination_name)
        if not isinstance(destination, FolderTarget):
            return JSONErrorResponse(f"Invalid destination '{destination_name}': not a folder target.", status_code=400)
        if not destination:
            return JSONErrorResponse(f"No such target '{destination_name}'.", status_code=400)
        destination_path = destination.folder

    offpeak = 'offpeak' in form
    search_filters = {}
    if search_filter := form.get("series_description"):
        search_filters["SeriesDescription"] = [x.strip() for x in search_filter.split(",")]
    if search_filter := form.get("study_description"):
        search_filters["StudyDescription"] =  [x.strip() for x in search_filter.split(",")]

    try:
        QueryPipeline.create(accession.split(","), search_filters, node, destination_path, offpeak=offpeak)
    except Exception as e:
        logger.exception(f"Error creating query pipeline for accession {accession}.")
        return JSONErrorResponse(str(e))

    return JSONResponse({"status": "success"})

@router.get("/query/jobs")
@requires(["authenticated", "admin"], redirect="login")
async def query_jobs(request):
    """
    Returns a list of all query jobs. 
    """
    tasks_info = []
    try:
        with Connection(redis):
            query_tasks = list(QueryPipeline.get_all())
    except Exception as e:
        logger.exception("Error retrieving query tasks.")
        return JSONErrorResponse("Error retrieving query tasks.", status_code=500)

    for task in query_tasks:
        task_dict: Dict[str,Any] = dict(id=task.id, 
                                status=task.get_status(), 
                                parameters=dict(accession=task.kwargs.get('accession','')), 
                                created_at=1000*datetime.timestamp(task.created_at) if task.created_at else "",
                                enqueued_at=1000*datetime.timestamp(task.enqueued_at) if task.enqueued_at else "", 
                                result=task.result if task.get_status() != "failed" else task.meta.get("failed_reason",""), 
                                meta=task.meta,
                                progress="")
        # if job.meta.get('completed') and job.meta.get('remaining'):
        #     task_dict["progress"] = f"{job.meta.get('completed')} / {job.meta.get('completed') + job.meta.get('remaining')}"
        # if job.meta.get('type',None) == "batch":
        n_started = task.meta.get('started',0)
        n_completed = task.meta.get('completed',0)
        n_total = task.meta.get('total',0)

        if task_dict["status"] == "finished":
            task_dict["progress"] = f"{n_total} / {n_total}"
        elif task_dict["status"] in ("deferred","started", "paused", "canceled"):
            task_dict["progress"] = f"{n_completed} / {n_total}"
        
        # if task_dict["status"] == "canceled" and 
        if task.meta.get('paused', False) and task_dict["status"] not in ("finished", "failed"):
            if n_started < n_completed: # TODO: this does not work
                task_dict["status"] = "pausing"
            else:
                task_dict["status"] = "paused"

        if task_dict["status"] in ("deferred", "started"):
            if n_started == 0:
                task_dict["status"] = "waiting"
            elif n_completed < n_total:
                task_dict["status"] = "running" 
            elif n_completed == n_total:
                task_dict["status"] = "finishing" 

        tasks_info.append(task_dict)
    return JSONResponse(dict(data=tasks_info))

@router.get("/query")
@requires(["authenticated", "admin"], redirect="login")
async def query(request):
    template = "dashboards/query.html"
    dicom_nodes = [name for name,node in config.mercure.targets.items() if isinstance(node, (DicomTarget, DicomWebTarget)) and node.direction in ("pull", "both")]
    destination_folders = [name for name,node in config.mercure.targets.items() if isinstance(node, FolderTarget)]
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
                logger.info(d)
                result_data.append( {x:d.get(x) for x in ["AccessionNumber", "PatientID", "StudyInstanceUID", "SeriesInstanceUID", "StudyDescription", "SeriesDescription", "NumberOfSeriesRelatedInstances"]} )
            return JSONResponse({"status": "completed", "result": result_data})
        return JSONResponse({"status": "pending", "job_id": job.id})

    node_name = form.get("dicom_node")
    accessions = form.get("accessions", "").split(",")
    
    search_filters = {}
    if search_filter:= form.get("series_description"):
        search_filters["SeriesDescription"] = [x.strip() for x in search_filter.split(",")]
    if search_filter:= form.get("study_description"):
        search_filters["StudyDescription"] =  [x.strip() for x in search_filter.split(",")]

    node = config.mercure.targets.get(node_name)
    if not isinstance(node, (DicomWebTarget, DicomTarget)):
        return JSONErrorResponse(f"Invalid DICOM node '{node_name}'.", status_code=400)
    
    try:
        with Connection(redis):
            job = CheckAccessionsTask().create_job(accessions=accessions, node=node, search_filters=search_filters)
            CheckAccessionsTask.queue().enqueue_job(job)
    except Exception as e:
        logger.exception("Error during accessions check task creation")
        return JSONErrorResponse(str(e), status_code=500)

    return JSONResponse({"status": "pending", "job_id": job.id})