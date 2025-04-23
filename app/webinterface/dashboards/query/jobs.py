"""
jobs.py
=======
"""

import dataclasses
import shutil
import subprocess
import time
import typing
from dataclasses import dataclass
# Standard python includes
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union, cast

# App-specific includes
import common.config as config
import pyfakefs.fake_pathlib
import rq
from common import helper
from common.types import DicomTarget, DicomWebTarget
from dispatch.target_types.base import ProgressInfo
from dispatch.target_types.registry import get_handler
from redis import Redis
from rq import Queue, get_current_job
from rq.job import Dependency, Job, JobStatus
from tests.getdcmtags import process_dicom
from webinterface.common import redis, rq_fast_queue, rq_slow_queue
from webinterface.dashboards.common import ClassBasedRQTask

# Starlette-related includes


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
class CheckAccessionsTask(ClassBasedRQTask):
    type: str = "check_accessions"
    _queue: str = rq_fast_queue.name

    def execute(self, *, accessions: List[str], node: Union[DicomTarget, DicomWebTarget],
                search_filters: Dict[str, List[str]] = {}):
        """
        Check if the given accessions exist on the node using a DICOM query.
        """
        results = []
        try:
            for accession in accessions:
                found_ds_list = get_handler(node).find_from_target(node, accession, search_filters)
                if not found_ds_list:
                    raise ValueError("No series found with accession number {}".format(accession))
                results.extend(found_ds_list)
            return results
        except Exception as e:
            if not self._job:
                raise
            self._job.meta['failed_reason'] = str(e)
            self._job.save_meta()  # type: ignore
            if self.parent and (job_parent := Job.fetch(self.parent)):
                if e.args:
                    job_parent.meta['failed_reason'] = f"{str(e)} ({str(e.args[0])})"
                else:
                    job_parent.meta['failed_reason'] = str(e)
                job_parent.save_meta()  # type: ignore
                Queue(job_parent.origin)._enqueue_job(job_parent, at_front=True)
            raise


@dataclass
class GetAccessionTask(ClassBasedRQTask):
    type: str = "get_accession"
    paused: bool = False
    offpeak: bool = False
    _queue: str = rq_slow_queue.name

    @classmethod
    def get_accession(cls, job_id, accession: str, node: Union[DicomTarget, DicomWebTarget],
                      search_filters: Dict[str, List[str]], path) -> Generator[ProgressInfo, None, None]:
        yield from get_handler(node).get_from_target(node, accession, search_filters, path)

    def execute(self, *, accession: str, node: Union[DicomTarget, DicomWebTarget],
                search_filters: Dict[str, List[str]], path: str, force_rule: Optional[str] = None):
        logger.info(f"Getting ACC {accession}")

        def error_handler(reason) -> None:
            logger.error(reason)
            if not job_parent:
                raise
            logger.info("Cancelling sibling jobs.")
            for subjob_id in job_parent.kwargs.get('subjobs', []):
                if subjob_id == job.id:
                    continue
                subjob = Job.fetch(subjob_id)
                if subjob.get_status() not in ('finished', 'canceled', 'failed'):
                    subjob.cancel()
            job_parent.get_meta()
            logger.info("Cancelled sibling jobs.")
            if not job_parent.meta.get("failed_reason"):
                job_parent.meta["failed_reason"] = reason
                job_parent.save_meta()  # type: ignore
                Queue(job_parent.origin)._enqueue_job(job_parent, at_front=True)  # Force the parent job to run and fail itself

        job = cast(Job, self._job)
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            job_parent = None
            if parent_id := self.parent:
                job_parent = Job.fetch(parent_id)

            if job_parent:
                job_parent.meta['started'] = job_parent.meta.get('started', 0) + 1
                job_parent.save_meta()  # type: ignore

            job.meta['started'] = 1
            job.meta['progress'] = "0 / Unknown"
            job.save_meta()  # type: ignore
            try:
                for info in self.get_accession(job.id, accession=accession, node=node, search_filters=search_filters,
                                               path=path):
                    job.meta['remaining'] = info.remaining
                    job.meta['completed'] = info.completed
                    job.meta['progress'] = info.progress
                    job.save_meta()  # type: ignore  # Save the updated meta data to the job
                    logger.info(info.progress)
            except Exception as e:
                error_handler(f"Failure during retrieval of accession {accession}: {e}")
                raise
            if job_parent:
                if job_parent.kwargs["move_promptly"]:
                    try:
                        self.move_to_destination(path, job_parent.kwargs["destination"], job_parent.id, node, force_rule)
                    except Exception as e:
                        error_handler(f"Failure during move to destination of accession {accession}: {e}")
                        raise

                job_parent.get_meta()  # there is technically a race condition here...
                job_parent.meta['completed'] += 1
                job_parent.meta['progress'] = (f"{job_parent.meta['started'] } /"
                                               f" {job_parent.meta['completed'] } / {job_parent.meta['total']}")
                job_parent.save_meta()  # type: ignore

        except Exception as e:
            error_handler(f"Failure with accession {accession}: {e}")
            raise

        return "Job complete"


@dataclass
class MainTask(ClassBasedRQTask):
    type: str = "batch"
    started: int = 0
    completed: int = 0
    total: int = 0
    paused: bool = False
    offpeak: bool = False
    _queue: str = rq_slow_queue.name

    def execute(self, *, accessions, subjobs, path: str, destination: Optional[str], move_promptly: bool,
                node: Union[DicomTarget, DicomWebTarget], force_rule: Optional[str] = None) -> str:
        job = cast(Job, self._job)
        job.get_meta()
        for job_id in job.kwargs.get('subjobs', []):
            subjob = Job.fetch(job_id)
            if (status := subjob.get_status()) != 'finished':
                raise Exception(f"Subjob {subjob.id} is {status}")
            if job.kwargs.get('failed', False):
                raise Exception("Failed")

        logger.info(f"Job completing {job.id}")
        if not move_promptly:
            logger.info("Moving files during completion as move_promptly==False")
            for p in Path(path).iterdir():
                if not p.is_dir():
                    continue
                try:
                    self.move_to_destination(str(p), destination, job.id, node, force_rule)
                except Exception as e:
                    err = (f"Failure during move to destination {destination}: {e}"
                           if destination
                           else f"Failure during move to {config.mercure.incoming_folder}: {e}")
                    logger.error(err)
                    job.meta["failed_reason"] = err
                    job.save_meta()  # type: ignore
                    raise

        logger.info(f"Removing job directory {path}")
        shutil.rmtree(path)
        job.meta["failed_reason"] = None
        job.save_meta()  # type: ignore

        return "Job complete"


class QueryPipeline():
    job: Job
    connection: Redis

    def __init__(self, job: Union[Job, str], connection: Redis = redis):
        self.connection = connection
        if isinstance(job, str):
            if not (result := Job.fetch(job, connection=self.connection)):
                raise Exception("Invalid Job ID")
            self.job = result
        else:
            self.job = job
        assert self.job.meta.get('type') == 'batch', f"Job type must be batch, got {self.job.meta['type']}"

    @classmethod
    def create(cls, accessions: List[str], search_filters: Dict[str, List[str]],
               dicom_node: Union[DicomWebTarget, DicomTarget], destination_path: Optional[str],
               offpeak: bool = False, force_rule: Optional[str] = None, redis_server=None
               ) -> 'QueryPipeline':
        """
        Create a job to process the given accessions and store them in the specified destination path.
        """
        connection = redis_server or redis
        get_accession_jobs: List[Job] = []
        check_job = CheckAccessionsTask().create_job(connection,
                                                     accessions=accessions,
                                                     search_filters=search_filters,
                                                     node=dicom_node)
        for accession in accessions:
            get_accession_task = GetAccessionTask(offpeak=offpeak).create_job(
                connection,
                accession=str(accession),
                node=dicom_node,
                force_rule=force_rule,
                search_filters=search_filters,
                rq_options=dict(
                    depends_on=cast(List[Union[Dependency, Job]], [check_job]),
                    timeout=30 * 60,
                    result_ttl=-1
                )
            )
            get_accession_jobs.append(get_accession_task)
        depends = Dependency(
            jobs=cast(List[Union[Job, str]], get_accession_jobs),
            allow_failure=True,    # allow_failure defaults to False
        )
        main_job = MainTask(total=len(get_accession_jobs), offpeak=offpeak).create_job(
            connection,
            accessions=accessions,
            subjobs=[check_job.id] + [j.id for j in get_accession_jobs],
            destination=destination_path,
            node=dicom_node,
            move_promptly=True,
            rq_options=dict(depends_on=depends, timeout=-1, result_ttl=-1),
            force_rule=force_rule
        )
        check_job.meta["parent"] = main_job.id
        for j in get_accession_jobs:
            j.meta["parent"] = main_job.id
            j.kwargs["path"] = Path(config.mercure.jobs_folder) / str(main_job.id) / j.kwargs['accession']
            j.kwargs["path"].mkdir(parents=True)

        main_job.kwargs["path"] = Path(config.mercure.jobs_folder) / str(main_job.id)

        CheckAccessionsTask.queue(connection).enqueue_job(check_job)
        for j in get_accession_jobs:
            GetAccessionTask.queue(connection).enqueue_job(j)
        MainTask.queue(connection).enqueue_job(main_job)

        wrapped_job = cls(main_job, connection)
        if offpeak and not helper._is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time()):
            wrapped_job.pause()

        return wrapped_job

    def __bool__(self) -> bool:
        return bool(self.job)

    def pause(self) -> None:
        """
        Pause the current job, including all its subjobs.
        """
        for job_id in self.job.kwargs.get('subjobs', []):
            subjob = Job.fetch(job_id, connection=self.connection)
            if subjob and (subjob.is_deferred or subjob.is_queued):
                logger.debug(f"Pausing {subjob}")
                subjob.meta['paused'] = True
                subjob.save_meta()  # type: ignore
                subjob.cancel()
        self.job.get_meta()
        self.job.meta['paused'] = True
        self.job.save_meta()  # type: ignore

    def resume(self) -> None:
        """
        Resume a paused job by unpausing all its subjobs
        """
        for subjob_id in self.job.kwargs.get('subjobs', []):
            subjob = Job.fetch(subjob_id, connection=self.connection)
            if subjob and subjob.meta.get('paused', None):
                subjob.meta['paused'] = False
                subjob.save_meta()  # type: ignore
                Queue(subjob.origin, connection=self.connection).canceled_job_registry.requeue(subjob_id)
        self.job.get_meta()
        self.job.meta['paused'] = False
        self.job.save_meta()  # type: ignore

    def retry(self) -> None:
        """
        Retry a failed job by enqueuing it again
        """
        # job.meta["retries"] = job.meta.get("retries", 0) + 1
        # if job.meta["retries"] > 3:
        #     return False
        logger.info(f"Retrying {self.job}")
        for subjob in self.get_subjobs():
            meta = subjob.get_meta()
            if (status := subjob.get_status()) in ("failed", "canceled"):
                logger.info(f"Retrying {subjob} ({status}) {meta}")
                if status == "failed" and (job_path := Path(subjob.kwargs['path'])).exists():
                    shutil.rmtree(job_path)  # Clean up after a failed job
                Queue(subjob.origin, connection=self.connection).enqueue_job(subjob)
        Queue(self.job.origin, connection=self.connection).enqueue_job(self.job)

    @classmethod
    def update_all_offpeak(cls) -> None:
        """
        Resume or pause offpeak jobs based on whether the current time is within offpeak hours.
        """
        config.read_config()
        is_offpeak = helper._is_offpeak(config.mercure.offpeak_start, config.mercure.offpeak_end, datetime.now().time())
        for pipeline in QueryPipeline.get_all():
            pipeline.update_offpeak(is_offpeak)

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
        return (j for j in (Queue(self.job.origin, connection=self.connection).fetch_job(job)
                for job in self.job.kwargs.get('subjobs', []))
                if j is not None)

    def get_status(self) -> JobStatus:
        return cast(JobStatus, self.job.get_status())

    def get_meta(self) -> Any:
        return cast(dict, self.job.get_meta())

    @property
    def meta(self) -> typing.Dict:
        return cast(dict, self.job.meta)

    @property
    def is_failed(self) -> bool:
        return cast(bool, self.job.is_failed)

    @property
    def is_finished(self) -> bool:
        return cast(bool, self.job.is_finished)

    @property
    def is_paused(self) -> bool:
        return cast(bool, self.meta.get("paused", False))

    @property
    def id(self) -> str:
        return cast(str, self.job.id)

    @property
    def kwargs(self) -> typing.Dict:
        try:
            return cast(dict, self.job.kwargs)
        except rq.exceptions.DeserializationError:
            logger.info(f"Failed to deserialize job kwargs: {self.job.data}")
            raise

    @property
    def result(self) -> Any:
        return self.job.result

    @property
    def created_at(self) -> datetime:
        return cast(datetime, self.job.created_at)

    @property
    def enqueued_at(self) -> datetime:
        return cast(datetime, self.job.enqueued_at)

    @classmethod
    def get_all(cls, type: str = "batch", connection: Redis = redis) -> Generator['QueryPipeline', None, None]:
        """
        Get all jobs of a given type from the queue
        """
        job_ids = set()

        registries = [
            rq_slow_queue.started_job_registry,     # Returns StartedJobRegistry
            rq_slow_queue.deferred_job_registry,    # Returns DeferredJobRegistry
            rq_slow_queue.finished_job_registry,    # Returns FinishedJobRegistry
            rq_slow_queue.failed_job_registry,      # Returns FailedJobRegistry
            rq_slow_queue.scheduled_job_registry,   # Returns ScheduledJobRegistry
            rq_slow_queue.canceled_job_registry,    # Returns CanceledJobRegistry
        ]
        for registry in registries:
            for j_id in registry.get_job_ids():
                job_ids.add(j_id)

        for j_id in rq_slow_queue.job_ids:
            job_ids.add(j_id)

        jobs = (Job.fetch(j_id, connection) for j_id in job_ids)

        return (QueryPipeline(j, connection) for j in jobs if j and j.get_meta().get("type") == type)
