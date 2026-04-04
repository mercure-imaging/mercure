"""
nomad_runtime.py
================
Nomad implementation of the mercure container runtime.

Nomad dispatches jobs asynchronously: run() returns as soon as the job is
submitted, so process_series does not wait for the container to finish.
"""

import json
import os
from pathlib import Path
from typing import Optional

import nomad

import common.config as config
import common.monitor as monitor
from common.types import Module, Task, TaskProcessing
from common.version import mercure_version
from jinja2 import Template
from process.runtime_base import ContainerRuntime
from typing import cast

logger = config.get_logger()


class NomadRuntime(ContainerRuntime):
    """Dispatches processing jobs to a Nomad cluster."""

    supports_multi_step = False
    is_async = True

    async def run(
        self,
        task: Task,
        folder: Path,
        file_count_begin: int,
        task_processing: TaskProcessing,
    ) -> bool:
        nomad_connection = nomad.Nomad(host="172.17.0.1", timeout=5)  # type: ignore

        if not task.process:
            return False

        module: Module = cast(Module, task_processing.module_config)
        if not module.docker_tag:
            logger.error("No docker tag supplied")
            return False

        with open("nomad/mercure-processor-template.nomad", "r") as f:
            rendered = Template(f.read()).render(
                image=module.docker_tag,
                mercure_tag=mercure_version.get_image_tag(),
                constraints=module.constraints,
                resources=module.resources,
                uid=os.getuid(),
            )
        logger.debug("----- job definition -----")
        logger.debug(rendered)
        try:
            job_definition = nomad_connection.jobs.parse(rendered)
        except nomad.api.exceptions.BadRequestNomadException as err:  # type: ignore
            logger.error(err)
            print(err.nomad_resp.reason)
            print(err.nomad_resp.text)
            return False

        job_definition["ID"] = f"processor-{task_processing.module_name}"
        job_definition["Name"] = f"processor-{task_processing.module_name}"
        nomad_connection.job.register_job(job_definition["ID"], dict(Job=job_definition))

        meta = {"PATH": folder.name}
        logger.debug(meta)
        job_info = nomad_connection.job.dispatch_job(
            f"processor-{task_processing.module_name}", meta=meta
        )
        with open(folder / "nomad_job.json", "w") as json_file:
            json.dump(job_info, json_file, indent=4)

        monitor.send_task_event(
            monitor.task_event.PROCESS_BEGIN,
            task.id,
            file_count_begin,
            task_processing.module_name,
            "Processing job dispatched",
        )
        return True

    def validate_image(self, tag: str) -> Optional[str]:
        """
        Nomad pulls images at dispatch time.  Try the Docker SDK for
        pre-validation; skip gracefully if Docker is not available.
        """
        try:
            import docker

            client = docker.from_env()
            try:
                client.images.get(tag)
                return None
            except docker.errors.ImageNotFound:
                try:
                    client.images.get_registry_data(tag)
                    return None
                except docker.errors.APIError as e:
                    if e.response.status_code == 403:
                        return (
                            "A container image with this tag does not exist "
                            "locally or in the Docker Hub registry."
                        )
                    return f"Failed to retrieve registry data: {e}"
                except Exception as e:
                    return f"Unexpected error retrieving registry data: {e}"
            except Exception as e:
                return f"Unexpected error: {e}"
        except Exception:
            return None  # Docker not available in this environment; skip validation
