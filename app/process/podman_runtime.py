"""
podman_runtime.py
=================
Podman implementation of the mercure container runtime.

Uses the podman-py SDK via the Podman REST socket.  The socket path is
read from CONTAINER_HOST (Podman's standard env var); for rootless
installations without CONTAINER_HOST set it falls back to the per-user
default at unix:///run/user/<uid>/podman/podman.sock.

When mercure itself runs inside Docker, mount the host Podman socket into
the processor container and set both CONTAINER_HOST and MERCURE_HOST_DATA_PATH
(see get_runtime() in runtime_base.py).
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import podman
from podman.errors import APIError, ContainerError, ImageNotFound

import common.config as config
from common.types import Module
from process.runtime_base import LocalContainerRuntime, _pull_throttle

logger = config.get_logger()

_CONTAINER_TIMEOUT = 3600  # seconds before a hung container is killed


class PodmanRuntime(LocalContainerRuntime):
    """Runs processing containers via the Podman SDK (podman-py)."""

    # With rootless Podman, uid 0 inside the container maps to the calling
    # user's uid on the host — root-in-container cannot escape to the host.
    # The support_root_modules gate is therefore not needed for Podman.
    root_requires_approval = False

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    @property
    def _podman_client(self) -> podman.PodmanClient:
        if self._client is None:
            if os.environ.get("CONTAINER_HOST"):
                # Reads CONTAINER_HOST automatically — covers the docker-in-docker
                # socket case and any explicit override.
                self._client = podman.PodmanClient.from_env()
            else:
                # Default rootless socket for the current user.
                socket = f"unix:///run/user/{os.getuid()}/podman/podman.sock"
                self._client = podman.PodmanClient(base_url=socket)
        return self._client

    # ------------------------------------------------------------------ #
    # Image name normalisation                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _qualify_image(tag: str) -> str:
        """
        Ensure *tag* includes an explicit registry hostname.

        Podman does not default to docker.io for unqualified names and may
        interactively prompt for a registry.  This method applies the same
        defaulting logic Docker uses.

        Examples::

            ubuntu:22.04            -> docker.io/library/ubuntu:22.04
            myorg/myimage:latest    -> docker.io/myorg/myimage:latest
            docker.io/myorg/img     -> docker.io/myorg/img       (unchanged)
            quay.io/biocontainers/x -> quay.io/biocontainers/x  (unchanged)
            localhost/myimage       -> localhost/myimage          (unchanged)
        """
        digest = ""
        if "@" in tag:
            tag, digest = tag.split("@", 1)
            digest = "@" + digest

        # Faithfully implements github.com/distribution/reference splitDockerDomain:
        # only inspect the first path component for a domain indicator when
        # there IS a slash — a bare "image:tag" with no slash always defaults
        # to docker.io/library/.
        if "/" in tag:
            first = tag.split("/")[0]
            # A dot or colon anywhere in the first component → it's a hostname.
            # (Colons here mean host:port, e.g. "registry.example.com:5000".)
            if "." in first or ":" in first or first == "localhost":
                return tag + digest

        if "/" not in tag:
            return f"docker.io/library/{tag}{digest}"
        return f"docker.io/{tag}{digest}"

    # ------------------------------------------------------------------ #
    # LocalContainerRuntime hooks                                          #
    # ------------------------------------------------------------------ #

    def _pull_image(self, tag: str) -> None:
        tag = self._qualify_image(tag)
        pulled = self._podman_client.images.pull(tag)
        if pulled is not None:
            digests = pulled.attrs.get("RepoDigests") or []
            if digests:
                logger.info(f"Using DIGEST {digests[0]}")
        try:
            self._podman_client.images.prune(filters={"dangling": True})
        except Exception:
            pass  # prune is best-effort

    def _detect_monai(self, tag: str) -> Optional[list]:
        tag = self._qualify_image(tag)
        try:
            raw = self._podman_client.containers.run(
                tag, command="cat /etc/monai/app.json", entrypoint=""
            )
            manifest = json.loads(raw.decode("utf-8"))
            logger.debug("Detected MONAI MAP, using command from manifest.")
            cmd = manifest["command"]
            return cmd if isinstance(cmd, list) else cmd.split()
        except ContainerError:
            return None  # image exists but has no MONAI manifest — that's fine
        except ImageNotFound:
            raise Exception(f"Podman image {tag} not found, aborting.")
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
        tag = self._qualify_image(tag)
        client = self._podman_client

        # When mercure runs inside Docker and talks to a host Podman socket
        # via CONTAINER_HOST, folder is a container-internal path.
        # MERCURE_HOST_DATA_PATH provides the host-side equivalent of
        # /opt/mercure/data so bind-mounts reach the right place on the host.
        host_data_path = os.environ.get("MERCURE_HOST_DATA_PATH")
        if host_data_path:
            real_folder = Path(host_data_path) / "processing" / folder.stem
            logger.info(f"Using host-side folder: {real_folder}")
        else:
            real_folder = folder

        # in/out dirs are unique per job (UUID-named folder) so ,Z (private
        # SELinux label) is safe and more secure.
        volumes: Dict[str, Dict[str, str]] = {
            str(real_folder / "in"):  {"bind": container_in_dir,  "mode": "rw,Z"},
            str(real_folder / "out"): {"bind": container_out_dir, "mode": "rw,Z"},
        }

        # Additional volumes are user-configured and may be shared across
        # parallel runs, so use ,z (shared label).
        for vol_src, vol_cfg in additional_volumes.items():
            mode = vol_cfg.get("mode", "rw")
            volumes[vol_src] = {"bind": vol_cfg.get("bind", vol_src), "mode": f"{mode},z"}

        # Persistence folder is shared across all parallel runs of the same
        # module, so use ,z (shared label) rather than ,Z (private).
        if persistence_mount:
            p_src = persistence_mount[0]
            if host_data_path and p_src.startswith(config.mercure.persistence_folder):
                rel = Path(p_src).relative_to(config.mercure.persistence_folder)
                p_src = str(Path(host_data_path) / "persistence" / rel)
            volumes[p_src] = {"bind": persistence_mount[1], "mode": "rw,z"}

        runtime_kwargs: Dict[str, Any] = {}
        if config.mercure.processing_runtime:
            runtime_kwargs["runtime"] = config.mercure.processing_runtime

        set_command: Dict[str, Any] = {}
        if monai_command:
            set_command = {"entrypoint": "", "command": monai_command}

        if requires_root:
            logger.debug("Executing module as root.")

        logger.info({
            "tag": tag, "volumes": volumes,
            "environment": environment, "arguments": arguments,
        })

        container = None
        try:
            container = client.containers.run(
                tag,
                volumes=volumes,
                environment=environment,
                **runtime_kwargs,
                **set_command,
                **arguments,
                detach=True,
            )

            result = container.wait(timeout=_CONTAINER_TIMEOUT)

            logs = ""
            raw = container.logs(timestamps=True)
            if raw is not None:
                logs = raw if isinstance(raw, str) else raw.decode("utf-8")

            exit_code = result.get("StatusCode", 1) if isinstance(result, dict) else int(result or 0)
            return exit_code, logs

        except APIError as e:
            raise Exception(f"Podman API error running container {tag}: {e}") from e
        except ImageNotFound as e:
            raise Exception(f"Image for tag {tag} not found.") from e
        finally:
            if container is not None:
                try:
                    container.stop(timeout=10)
                except Exception:
                    pass  # already stopped or never started
                container.remove()

    # ------------------------------------------------------------------ #
    # Image operations (used by the web UI)                               #
    # ------------------------------------------------------------------ #

    def list_local_images(self) -> Optional[List[str]]:
        try:
            images = []
            for image in self._podman_client.images.list():
                if image.tags:
                    images.append(image.tags[0])
            return sorted(images)
        except Exception as e:
            logger.error(f"Error listing local Podman images: {e}")
            return None

    def validate_image(self, tag: str) -> Optional[str]:
        tag = self._qualify_image(tag)
        try:
            client = self._podman_client
        except Exception as e:
            return f"Unable to connect to Podman socket: {e}"
        try:
            client.images.get(tag)
            return None
        except ImageNotFound:
            try:
                client.images.get_registry_data(tag)
                return None
            except APIError as e:
                err = str(e).lower()
                if "unauthorized" in err or "403" in err or "authentication" in err:
                    return f"Access denied pulling {tag}. Check registry credentials."
                if "not found" in err or "does not exist" in err or "no such" in err:
                    return f"Image {tag} not found locally or in the registry."
                return f"Failed to retrieve registry data for {tag}: {str(e)[:300]}"
            except Exception as e:
                return f"Unexpected error retrieving registry data for {tag}: {e}"
        except APIError as e:
            return (
                f"Unable to read image list: {e}. "
                "Check Podman socket and any firewall settings."
            )
        except Exception as e:
            return f"Unexpected error: {e}"
