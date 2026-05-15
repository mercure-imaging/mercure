"""
docker_runtime.py
=================
Docker implementation of the mercure container runtime.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docker
from docker.types import Mount

import common.config as config
import common.helper as helper
from common.types import Module
from process.runtime_base import LocalContainerRuntime, _pull_throttle

logger = config.get_logger()


class DockerRuntime(LocalContainerRuntime):
    """Runs processing containers via the Docker SDK."""

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    @property
    def _docker_client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    # ------------------------------------------------------------------ #
    # LocalContainerRuntime hooks                                          #
    # ------------------------------------------------------------------ #

    def _pull_image(self, tag: str) -> None:
        pulled = self._docker_client.images.pull(tag)
        if pulled is not None:
            digests = pulled.attrs.get("RepoDigests")
            digest_string = digests[0] if digests else "None"
            logger.info("Using DIGEST " + digest_string)
        prune_result = self._docker_client.images.prune(filters={"dangling": True})
        logger.info(prune_result)

    def _detect_monai(self, tag: str) -> Optional[list]:
        try:
            raw = self._docker_client.containers.run(
                tag, command="cat /etc/monai/app.json", entrypoint=""
            )
            manifest = json.loads(raw.decode("utf-8"))
            logger.debug("Detected MONAI MAP, using command from manifest.")
            cmd = manifest["command"]
            return cmd if isinstance(cmd, list) else cmd.split()
        except docker.errors.ContainerError:
            return None  # image exists but has no MONAI manifest – that's fine
        except docker.errors.NotFound:
            raise Exception(f"Docker tag {tag} not found, aborting.")
        except (json.decoder.JSONDecodeError, KeyError):
            raise Exception("Failed to parse MONAI app manifest.")

    async def _execute(
        self,
        tag: str,
        folder: Path,
        container_in_dir: str,
        container_out_dir: str,
        environment: Dict[str, str],
        additional_volumes: Dict,
        arguments: Dict,
        monai_command: Optional[list],
        module: Module,
        persistence_mount: Optional[Tuple[str, str]],
        requires_root: bool,
    ) -> Tuple[int, str]:
        client = self._docker_client

        # When mercure itself runs inside Docker we need the host-side path
        # of the named volume so the spawned container can bind-mount it.
        real_folder = folder
        if helper.get_runner() == "docker":
            try:
                base_path = Path(
                    client.api.inspect_volume("mercure_data")["Options"]["device"]
                )
            except Exception:
                base_path = Path("/opt/mercure/data")
                logger.error(
                    f"Unable to find volume 'mercure_data'; "
                    f"assuming data directory is {base_path}"
                )
            logger.info(f"Base path: {base_path}")
            real_folder = base_path / "processing" / folder.stem

        mounts = [
            Mount(source=str(real_folder / "in"), target=container_in_dir, type="bind"),
            Mount(source=str(real_folder / "out"), target=container_out_dir, type="bind"),
        ]
        if persistence_mount:
            mounts.append(
                Mount(source=persistence_mount[0], target=persistence_mount[1], type="bind")
            )

        runtime_kwargs: Dict[str, Any] = {}
        if config.mercure.processing_runtime:
            runtime_kwargs["runtime"] = config.mercure.processing_runtime

        set_command: Dict[str, Any] = {}
        if monai_command:
            set_command = {"entrypoint": "", "command": monai_command}

        user_kwargs: Dict[str, Any] = {}
        if not requires_root:
            user_kwargs = {
                "user": f"{os.getuid()}:{os.getegid()}",
                "group_add": [os.getgid()],
            }
        else:
            logger.debug("Executing module as root.")

        logger.info(
            {
                "docker_tag": tag,
                "mounts": mounts,
                "volumes": additional_volumes,
                "environment": environment,
                "arguments": arguments,
            }
        )

        container = None
        try:
            container = client.containers.run(
                tag,
                mounts=mounts,
                volumes=additional_volumes,
                environment=environment,
                **runtime_kwargs,
                **set_command,
                **arguments,
                **user_kwargs,
                detach=True,
            )
            docker_result = container.wait()
            logger.info(docker_result)

            raw = container.logs(timestamps=True)
            logs = raw.decode("utf-8") if raw is not None else ""

            # Fix output-file ownership with a lightweight busybox container.
            try:
                busybox_tag = "busybox:stable-musl"
                if (
                    datetime.now()
                    - _pull_throttle.get(busybox_tag, datetime.fromisocalendar(1, 1, 1))
                ).total_seconds() > 86400:
                    client.images.pull(busybox_tag)
                    _pull_throttle[busybox_tag] = datetime.now()
            except Exception:
                logger.exception("Could not pull busybox")

            # If mercure is NOT running inside Docker, use userns_mode=host so
            # the chown applies the real uid, not the remapped one.
            set_usrns: Dict[str, Any] = (
                {} if helper.get_runner() == "docker" else {"userns_mode": "host"}
            )
            client.containers.run(
                "busybox:stable-musl",
                mounts=mounts,
                **set_usrns,
                command=f"chown -R {os.getuid()}:{os.getegid()} {container_out_dir}",
                detach=False,
            )

            exit_code: int = docker_result.get("StatusCode", 1)
            return exit_code, logs

        except docker.errors.APIError as e:
            raise Exception(f"Docker API error running container {tag}: {e}") from e
        except docker.errors.ImageNotFound as e:
            raise Exception(f"Image for tag {tag} not found.") from e
        finally:
            if container is not None:
                container.remove()

    # ------------------------------------------------------------------ #
    # Image operations (used by the web UI)                               #
    # ------------------------------------------------------------------ #

    def list_local_images(self) -> Optional[List[str]]:
        try:
            images = []
            for image in self._docker_client.images.list():
                if image.tags:
                    images.append(image.tags[0])
            return sorted(images)
        except Exception as e:
            logger.error(f"Error listing local Docker images: {e}")
            return None

    def validate_image(self, tag: str) -> Optional[str]:
        try:
            client = self._docker_client
        except Exception as e:
            return f"Unable to connect to Docker: {e}"
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
                        "A Docker container with this tag does not exist "
                        "locally or in the Docker Hub registry."
                    )
                return f"Failed to retrieve Docker Registry data about this docker tag: {e}"
            except Exception as e:
                return (
                    f"Unexpected error retrieving Docker Registry data "
                    f"about this docker tag: {e}"
                )
        except docker.errors.APIError as e:
            return (
                f"Unable to read container list: {e}. "
                "Check server logs, Docker installation, and any firewall settings."
            )
        except Exception as e:
            return (
                f"Unexpected error: {e}. "
                "Check server logs, Docker installation, and any firewall settings."
            )
