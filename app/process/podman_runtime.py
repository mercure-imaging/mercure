"""
podman_runtime.py
=================
Podman implementation of the mercure container runtime.

Uses the `podman` CLI via subprocess.  Designed for rootless Podman:
uid mapping is automatic so no busybox chown step is needed.
"""

import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import common.config as config
from common.types import Module
from process.runtime_base import LocalContainerRuntime

logger = config.get_logger()

# Maximum time (seconds) to wait for a processing container to exit.
# A container that exceeds this is killed and the job fails.
_CONTAINER_TIMEOUT = 3600  # 1 hour


class PodmanRuntime(LocalContainerRuntime):
    """Runs processing containers via the Podman CLI."""

    # With rootless Podman, uid 0 inside the container maps to the calling
    # user's uid on the host — root-in-container cannot escape to the host.
    # The support_root_modules gate is therefore not needed for Podman.
    root_requires_approval = False

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
        subprocess.run(
            ["podman", "pull", self._qualify_image(tag)],
            capture_output=True,
            check=False,
            timeout=600,
        )

    def _detect_monai(self, tag: str) -> Optional[list]:
        tag = self._qualify_image(tag)
        result = subprocess.run(
            ["podman", "run", "--rm", "--entrypoint=", tag, "cat", "/etc/monai/app.json"],
            capture_output=True,
            check=False,
            timeout=30,
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
        cmd = self._build_command(
            tag, folder, container_in_dir, container_out_dir,
            environment, additional_volumes, arguments, monai_command,
            module, persistence_mount,
        )
        logger.info(f"Podman command: {cmd}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge so line ordering is preserved
        )

        log_lines: List[str] = []

        async def _stream() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                ts = datetime.now().isoformat(timespec="seconds")
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                log_lines.append(f"{ts} {line}")
            await proc.wait()

        try:
            await asyncio.wait_for(_stream(), timeout=_CONTAINER_TIMEOUT)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            raise Exception(
                f"Container {tag} timed out after {_CONTAINER_TIMEOUT}s and was killed."
            )

        exit_code = proc.returncode if proc.returncode is not None else 1
        return exit_code, "\n".join(log_lines)

    def _build_command(
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
    ) -> List[str]:
        cmd = ["podman", "run", "--rm"]

        # in/out dirs are unique per job (UUID-named folder) so :Z (private
        # SELinux label) is safe and more secure.
        cmd += ["-v", f"{folder / 'in'}:{container_in_dir}:Z"]
        cmd += ["-v", f"{folder / 'out'}:{container_out_dir}:Z"]

        # Additional volumes are user-configured and may be shared across
        # parallel runs, so use :z (shared label).
        for vol_src, vol_cfg in additional_volumes.items():
            target = vol_cfg.get("bind", vol_src)
            mode = vol_cfg.get("mode", "rw")
            cmd += ["-v", f"{vol_src}:{target}:{mode},z"]

        # Persistence folder is shared across all parallel runs of the same
        # module, so use :z (shared label) rather than :Z (private).
        if persistence_mount:
            cmd += ["-v", f"{persistence_mount[0]}:{persistence_mount[1]}:z"]

        for k, v in environment.items():
            cmd += ["-e", f"{k}={v}"]

        # With rootless Podman, omitting --user means the container process
        # runs as uid 0 inside the container, which maps to the calling user's
        # uid on the host.  Files written to mounted volumes are therefore
        # owned by the mercure user — no busybox chown step needed.
        if module.requires_root:
            logger.debug("Executing module as root.")

        if config.mercure.processing_runtime:
            cmd += ["--runtime", config.mercure.processing_runtime]

        for k, v in arguments.items():
            cmd += [str(k), str(v)]

        cmd.append(tag)
        if monai_command:
            cmd += monai_command

        return cmd

    # ------------------------------------------------------------------ #
    # Image validation (used by the web UI)                               #
    # ------------------------------------------------------------------ #

    def validate_image(self, tag: str) -> Optional[str]:
        tag = self._qualify_image(tag)
        if subprocess.run(
            ["podman", "image", "exists", tag], check=False
        ).returncode == 0:
            return None
        pull = subprocess.run(
            ["podman", "pull", tag], capture_output=True, check=False, timeout=600
        )
        if pull.returncode == 0:
            return None
        stderr = pull.stderr.decode("utf-8", errors="replace").lower()
        if "unauthorized" in stderr or "403" in stderr or "authentication" in stderr:
            return f"Access denied pulling {tag}. Check registry credentials."
        if "not found" in stderr or "does not exist" in stderr or "no such" in stderr:
            return f"Image {tag} not found locally or in the registry."
        # Fall back to showing the raw error so the operator has something to act on.
        raw = pull.stderr.decode("utf-8", errors="replace").strip()
        return f"Failed to pull image {tag}: {raw[:300]}"
