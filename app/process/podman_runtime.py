"""
podman_runtime.py
=================
Podman implementation of the mercure container runtime.

Uses the `podman` CLI via subprocess.  Designed for rootless Podman:
uid mapping is automatic so no busybox chown step is needed.
"""

import json
import os
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
    # LocalContainerRuntime hooks                                          #
    # ------------------------------------------------------------------ #

    def _pull_image(self, tag: str) -> None:
        subprocess.run(["podman", "pull", tag], capture_output=True, check=False)

    def _detect_monai(self, tag: str) -> Optional[list]:
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
        # Podman runs on the host so folder paths need no remapping.
        cmd = ["podman", "run", "--rm"]

        # Bind-mount in/out dirs.  The :z label relabels for SELinux systems.
        cmd += ["-v", f"{folder / 'in'}:{container_in_dir}:z"]
        cmd += ["-v", f"{folder / 'out'}:{container_out_dir}:z"]

        # Additional volumes specified in the module config.
        for vol_src, vol_cfg in additional_volumes.items():
            target = vol_cfg.get("bind", vol_src)
            mode = vol_cfg.get("mode", "rw")
            cmd += ["-v", f"{vol_src}:{target}:{mode},z"]

        # Persistence volume.
        if persistence_mount:
            cmd += ["-v", f"{persistence_mount[0]}:{persistence_mount[1]}:z"]

        # Environment variables.
        for k, v in environment.items():
            cmd += ["-e", f"{k}={v}"]

        # User.  With rootless Podman the host uid maps to uid 0 inside the
        # container by default, so without --userns=keep-id, setting --user
        # to the host uid would map it to a *subuid* on the host, meaning
        # output files would be owned by a subuid that mercure cannot access.
        # --userns=keep-id makes Podman map the host uid to the same uid
        # inside the container, so file ownership is preserved correctly.
        if not module.requires_root:
            cmd += ["--userns=keep-id", "--user", f"{os.getuid()}:{os.getegid()}"]
        else:
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
        if subprocess.run(["podman", "image", "exists", tag]).returncode == 0:
            return None
        pull = subprocess.run(["podman", "pull", tag], capture_output=True)
        if pull.returncode != 0:
            return (
                "A container image with this tag does not exist "
                "locally or in the registry."
            )
        return None
