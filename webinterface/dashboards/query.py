
from webinterface.query import SimpleDicomClient
# Standard python includes
from datetime import datetime

# Starlette-related includes
from starlette.authentication import requires

# App-specific includes
from common.constants import mercure_defs
from webinterface.common import templates
import common.config as config
from starlette.responses import PlainTextResponse, JSONResponse
from webinterface.common import worker_queue
from rq import get_current_job

from .common import router
logger = config.get_logger()

def test_job(*,accession, node):
    config.read_config()
    c = SimpleDicomClient(node.ip, node.port, node.aet_target, config.mercure.incoming_folder)
    for identifier in c.getscu(accession):
        job = get_current_job()
        job.meta['failed'] = identifier.NumberOfFailedSuboperations
        job.meta['remaining'] = identifier.NumberOfRemainingSuboperations
        job.meta['completed'] = identifier.NumberOfCompletedSuboperations
        job.save_meta()
    return "Complete"

@router.post("/query")
@requires(["authenticated", "admin"], redirect="login")
async def query_post(request):
    form = await request.form()

    for n in config.mercure.dicom_retrieve.dicom_nodes:
        if n.name == form.get("dicom_node"):
            node = n
            break
    
    worker_queue.enqueue_call(test_job, kwargs=dict(accession=form.get("accession"), node=node), timeout='10m', result_ttl=-1)
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
            job_info.append(dict(id=j_id, 
                                 status=job.get_status(), 
                                 parameters=dict(accession=job.kwargs.get('accession','')), 
                                 enqueued_at=1000*datetime.timestamp(job.enqueued_at), 
                                 result=job.result, 
                                 meta=job.meta))
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