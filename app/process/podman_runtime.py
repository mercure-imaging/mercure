"""
podman_runtime.py
=================
Podman implementation of the mercure container runtime.

Uses the `podman` CLI via subprocess.  Designed for rootless Podman:
uid mapping is automatic so no busybox chown step is needed.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

import common.config as config
from common.types import Module
from process.runtime_base import LocalContainerRuntime

logger = config.get_logger()


class PodmanRuntime(LocalContainerRuntime):
    """Runs processing containers via the Podman CLI."""

    # ------------------------------------------------------------------ #
    # Image name normalisation                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _qualify_image(tag: str) -> str:
        """
        Ensure *tag* includes an explicit registry hostname.

        Podman does not default to docker.io for unqualified names and may
        interactively prompt for a registry, hanging subprocess calls.
        This method applies the same defaulting logic Docker uses.

        Examples::

            ubuntu:22.04            -> docker.io/library/ubuntu:22.04
            myorg/myimage:latest    -> docker.io/myorg/myimage:latest
            docker.io/myorg/img     -> docker.io/myorg/img       (unchanged)
            quay.io/biocontainers/x -> quay.io/biocontainers/x  (unchanged)
            localhost/myimage       -> localhost/myimage          (unchanged)
        """
        # Preserve any digest suffix (@sha256:...) so we don't mangle it.
        digest = ""
        if "@" in tag:
            tag, digest = tag.split("@", 1)
            digest = "@" + digest

        # A registry hostname is the first slash-delimited component and
        # contains a dot or colon, or is exactly "localhost".
        first = tag.split("/")[0]
        if "." in first or ":" in first or first == "localhost":
            return tag + digest  # already has a registry

        # No registry — apply docker.io.  Single-component names (no slash)
        # are official library images; multi-component names are user/org images.
        if "/" not in tag:
            return f"docker.io/library/{tag}{digest}"
        return f"docker.io/{tag}{digest}"

    # ------------------------------------------------------------------ #
    # LocalContainerRuntime hooks                                          #
    # ------------------------------------------------------------------ #

    def _pull_image(self, tag: str) -> None:
        subprocess.run(["podman", "pull", self._qualify_image(tag)], capture_output=True, check=False)

    def _detect_monai(self, tag: str) -> Optional[list]:
        tag = self._qualify_image(tag)
        result = subprocess.run(
            ["podman", "run", "--rm", "--entrypoint=", tag, "cat", "/etc/monai/app.json"],
            capture_output=True,
        )
        if result.returncode != 0:
            return None  # image exists but has no MONAI manifest – that's fine
        try:
            manifest = json.loads(result.stdout.decode("utf-8"))
            logger.debug("Detected MONAI MAP, using command from manifest.")
            cmd = manifest["command"]
            return cmd if isinstance(cmd, list) else cmd.split()
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
    ) -> Tuple[int, str]:
        tag = self._qualify_image(tag)
        # Podman runs on the host so folder paths need no remapping.
        cmd = ["podman", "run", "--rm"]

        # Bind-mount in/out dirs.  :Z gives each container a private SELinux label.
        cmd += ["-v", f"{folder / 'in'}:{container_in_dir}:Z"]
        cmd += ["-v", f"{folder / 'out'}:{container_out_dir}:Z"]

        # Additional volumes specified in the module config.
        for vol_src, vol_cfg in additional_volumes.items():
            target = vol_cfg.get("bind", vol_src)
            mode = vol_cfg.get("mode", "rw")
            cmd += ["-v", f"{vol_src}:{target}:{mode},Z"]

        # Persistence volume.
        if persistence_mount:
            cmd += ["-v", f"{persistence_mount[0]}:{persistence_mount[1]}:Z"]

        # Environment variables.
        for k, v in environment.items():
            cmd += ["-e", f"{k}={v}"]

        # With rootless Podman, omitting --user means the container process
        # runs as uid 0 inside the container, which maps to the calling user's
        # uid on the host.  Files written to mounted volumes are therefore
        # owned by the mercure user — no busybox chown step needed.
        #
        # uid 0 inside a rootless container is bounded by the user namespace
        # and cannot affect the host beyond what the calling user can do.
        if module.requires_root:
            logger.debug("Executing module as root.")

        if config.mercure.processing_runtime:
            cmd += ["--runtime", config.mercure.processing_runtime]

        # Extra arguments from the module config (dict of flag -> value).
        for k, v in arguments.items():
            cmd += [str(k), str(v)]

        cmd.append(tag)
        if monai_command:
            cmd += monai_command

        logger.info(f"Podman command: {cmd}")
        result = subprocess.run(cmd, capture_output=True)
        logs = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        return result.returncode, logs

    # ------------------------------------------------------------------ #
    # Image validation (used by the web UI)                               #
    # ------------------------------------------------------------------ #

    def validate_image(self, tag: str) -> Optional[str]:
        tag = self._qualify_image(tag)
        if subprocess.run(["podman", "image", "exists", tag]).returncode == 0:
            return None
        pull = subprocess.run(["podman", "pull", tag], capture_output=True)
        if pull.returncode != 0:
            return (
                "A container image with this tag does not exist "
                "locally or in the registry."
            )
        return None
