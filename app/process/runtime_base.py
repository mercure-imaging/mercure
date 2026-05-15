"""
runtime_base.py
===============
Abstract base classes for mercure container runtimes, plus shared template logic
for local runtimes (Docker and Podman).
"""

import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import common.config as config
import common.helper as helper
import common.monitor as monitor
from common.constants import mercure_names
from common.types import Module, Task, TaskProcessing

logger = config.get_logger()

# Shared pull-throttle dict: maps image tag -> last pull time.
# Module-level so it persists across runtime instances within a process.
# Subclasses access this via LocalContainerRuntime.pull_throttle rather than
# importing the private name directly.
_pull_throttle: Dict[str, datetime] = {}


class ContainerRuntime(ABC):
    """Minimal interface every runtime must implement."""

    # True if the runtime supports chained (multi-step) processing.
    supports_multi_step: bool = True

    # True if run() dispatches work asynchronously and returns before
    # the container finishes (e.g. Nomad).  False means run() blocks
    # until the container exits, and process_series handles cleanup.
    is_async: bool = False

    @abstractmethod
    async def run(
        self,
        task: Task,
        folder: Path,
        file_count_begin: int,
        task_processing: TaskProcessing,
    ) -> bool:
        """Execute one processing step.  Returns True on success."""
        ...

    @abstractmethod
    def validate_image(self, tag: str) -> Optional[str]:
        """Check that *tag* is accessible.  Returns an error message or None."""
        ...

    def list_local_images(self) -> Optional[List[str]]:
        """Return sorted list of locally available image tags, or None if unavailable."""
        return None


class LocalContainerRuntime(ContainerRuntime):
    """
    Template base for runtimes that run containers locally and synchronously
    (Docker and Podman).  Subclasses implement _pull_image, _detect_monai,
    and _execute; the shared run() method handles the rest.
    """

    # Set to False in subclasses where running as uid 0 inside the container
    # is inherently bounded (e.g. rootless Podman), so the support_root_modules
    # config gate does not need to apply.
    root_requires_approval: bool = True

    # Shared pull-throttle dict exposed for subclasses.  Use this instead of
    # importing the module-private _pull_throttle directly.
    pull_throttle = _pull_throttle

    # ------------------------------------------------------------------ #
    # Static helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def decode_task_json(json_string: Optional[str]) -> Any:
        if not json_string:
            return {}
        try:
            return json.loads(json_string)
        except json.decoder.JSONDecodeError:
            logger.error(f"Unable to convert JSON string: {json_string}")
            return {}

    @staticmethod
    def _build_environment(
        module: Module, container_in_dir: str, container_out_dir: str
    ) -> Dict[str, str]:
        module_env = LocalContainerRuntime.decode_task_json(module.environment)
        return {
            **module_env,
            "MERCURE_IN_DIR": container_in_dir,
            "MERCURE_OUT_DIR": container_out_dir,
            "MONAI_INPUTPATH": container_in_dir,
            "MONAI_OUTPUTPATH": container_out_dir,
            "HOLOSCAN_INPUT_PATH": container_in_dir,
            "HOLOSCAN_OUTPUT_PATH": container_out_dir,
        }

    @staticmethod
    def _prepare_input_files(folder: Path) -> None:
        (folder / "in").chmod(0o777)
        try:
            for k in (folder / "in").glob("**/*"):
                k.chmod(0o666)
        except PermissionError:
            raise Exception(
                "Unable to prepare input files for processor. "
                "The receiver may be running as root, which is no longer supported."
            )
        (folder / "out").chmod(0o777)

    @staticmethod
    def _fix_output_permissions(folder: Path) -> None:
        try:
            (folder / "out").chmod(0o755)
            for k in (folder / "out").glob("**/*"):
                if k.is_dir():
                    k.chmod(0o755)
            for k in (folder / "out").glob("**/*"):
                if k.is_file():
                    k.chmod(0o644)
        except Exception as e:
            logger.exception("Unable to set permissions on output files. " + str(e))

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _acquire_persistence(
        self,
        module: Module,
        task_processing: TaskProcessing,
        environment: Dict[str, str],
        lock_id: str,
        task_id: str,
    ) -> Optional[Tuple[Path, str, str]]:
        """
        Set up the persistence folder and create a lock file.
        Returns (lock_file, mount_source, mount_target) or None on failure.
        Also injects MODULE_PERSISTENCE_DIR into *environment*.
        """
        persistence_name = module.persistence_folder_name or task_processing.module_name
        mount_source = str(Path(config.mercure.persistence_folder) / persistence_name)
        mount_target = "/tmp/persistence"
        environment["MODULE_PERSISTENCE_DIR"] = mount_target
        logger.info("Mounting persistence folder: " + mount_source)
        try:
            os.makedirs(mount_source, exist_ok=True)
        except Exception:
            logger.error(f"Unable to create persistence folder {mount_source}")
        if not Path(mount_source).exists():
            logger.error(f"Persistence folder {mount_source} not found.")
            return None
        lock_file = Path(mount_source) / (lock_id + mercure_names.LOCK)
        try:
            lock_file.touch(exist_ok=False)
        except Exception:
            logger.error(f"Unable to create lock file {lock_file}", task_id)
            return None
        return lock_file, mount_source, mount_target

    # ------------------------------------------------------------------ #
    # Image pull throttle                                                  #
    # ------------------------------------------------------------------ #

    def _maybe_pull(self, tag: str) -> None:
        if tag in _pull_throttle:
            if (datetime.now() - _pull_throttle[tag]).total_seconds() < 3600:
                return
        try:
            _pull_throttle[tag] = datetime.now()
            logger.info(f"Checking for update of image {tag} ...")
            self._pull_image(tag)
            logger.info("Update done")
        except Exception:
            logger.info(
                "Couldn't check for module update "
                "(this is normal for unpublished modules)"
            )

    # ------------------------------------------------------------------ #
    # Abstract hooks                                                       #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _pull_image(self, tag: str) -> None:
        """Pull *tag* from the registry."""
        ...

    @abstractmethod
    def _detect_monai(self, tag: str) -> Optional[list]:
        """
        Return the command list from the MONAI app manifest if this image is
        a MONAI MAP, or None if it is not.  Raise on parse errors.
        """
        ...

    @abstractmethod
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
        """
        Run the container.  Returns (exit_code, combined_logs_string).
        Must not raise for non-zero exit codes – return the code instead.
        """
        ...

    # ------------------------------------------------------------------ #
    # Template run()                                                       #
    # ------------------------------------------------------------------ #

    async def run(
        self,
        task: Task,
        folder: Path,
        file_count_begin: int,
        task_processing: TaskProcessing,
    ) -> bool:
        if not task.process:
            return False

        module = cast(Module, task_processing.module_config)
        if not module.docker_tag:
            logger.error("No docker tag supplied")
            return False

        docker_tag = module.docker_tag
        container_in_dir = "/tmp/data"
        container_out_dir = "/tmp/output"

        environment = self._build_environment(module, container_in_dir, container_out_dir)
        additional_volumes: Dict[str, Any] = self.decode_task_json(module.additional_volumes)
        arguments: Dict[str, Any] = self.decode_task_json(module.docker_arguments)

        lock_id = str(uuid.uuid1())
        persistence_lock_file: Optional[Path] = None
        persistence_mount: Optional[Tuple[str, str]] = None
        if module.requires_persistence:
            result = self._acquire_persistence(
                module, task_processing, environment, lock_id, task.id
            )
            if result is None:
                return False
            persistence_lock_file, mount_source, mount_target = result
            persistence_mount = (mount_source, mount_target)

        monai_command: Optional[list] = self._detect_monai(docker_tag)
        requires_root = bool(module.requires_root) or (monai_command is not None)

        self._maybe_pull(docker_tag)

        processing_success = True
        try:
            if requires_root and self.root_requires_approval and not config.mercure.support_root_modules:
                raise Exception(
                    "This module requires execution as root, but "
                    "'support_root_modules' is not set to true in the configuration. Aborting."
                )

            self._prepare_input_files(folder)

            await monitor.async_send_task_event(
                monitor.task_event.PROCESS_MODULE_BEGIN,
                task.id,
                file_count_begin,
                task_processing.module_name,
                "Processing module running",
            )

            exit_code, logs = await self._execute(
                docker_tag,
                folder,
                container_in_dir,
                container_out_dir,
                environment,
                additional_volumes,
                arguments,
                monai_command,
                module,
                persistence_mount,
                requires_root,
            )

            logs = helper.localize_log_timestamps(logs, config)
            logger.info("=== MODULE OUTPUT - BEGIN ========================================")
            if not config.mercure.processing_logs.discard_logs:
                monitor.send_process_logs(task.id, task_processing.module_name, logs)
            logger.info(logs)
            logger.info("=== MODULE OUTPUT - END ==========================================")

            self._fix_output_permissions(folder)

            await monitor.async_send_task_event(
                monitor.task_event.PROCESS_MODULE_COMPLETE,
                task.id,
                file_count_begin,
                task_processing.module_name,
                "Processing module complete",
            )

            if exit_code != 0:
                logger.error(
                    f"Error while running container {docker_tag} - exit code {exit_code}",
                    task.id,
                )
                processing_success = False

        except Exception:
            logger.exception(f"Error while running container, tag: {docker_tag}")
            processing_success = False

        if (
            module.requires_persistence
            and persistence_lock_file is not None
            and persistence_lock_file.exists()
        ):
            try:
                persistence_lock_file.unlink()
            except Exception:
                logger.error(f"Error removing lock file {persistence_lock_file}", task.id)
                return False

        return processing_success


def get_runtime() -> ContainerRuntime:
    """Return the configured runtime based on MERCURE_RUNNER env var and config."""
    # Deferred imports to avoid circular dependencies.
    from process.docker_runtime import DockerRuntime
    from process.nomad_runtime import NomadRuntime
    from process.podman_runtime import PodmanRuntime

    runner = helper.get_runner()
    process_runner = config.mercure.process_runner

    if runner == "nomad" or process_runner == "nomad":
        logger.debug("Processing with Nomad.")
        return NomadRuntime()
    if runner == "podman" or process_runner == "podman":
        if runner == "docker" and not os.environ.get("CONTAINER_HOST"):
            # Podman runs on the host; when mercure itself runs inside Docker
            # the processing folder paths are container-internal paths, not
            # host paths, so volume mounts would point to the wrong place.
            # Solution: mount the host Podman socket into the processor container
            # and set CONTAINER_HOST to its path.  podman-py connects via that
            # socket and MERCURE_HOST_DATA_PATH maps container paths to host paths.
            raise Exception(
                "process_runner='podman' is not supported when mercure is running "
                "inside Docker (MERCURE_RUNNER='docker') unless CONTAINER_HOST is "
                "set to a host Podman socket and MERCURE_HOST_DATA_PATH is set to "
                "the host-side data directory. Use process_runner='docker' otherwise."
            )
        logger.debug("Processing with Podman.")
        return PodmanRuntime()
    if runner in ("docker", "systemd"):
        logger.debug("Processing with Docker.")
        return DockerRuntime()
    raise Exception(
        f"Unable to determine a valid runtime for processing "
        f"(MERCURE_RUNNER={runner!r}, process_runner={process_runner!r})"
    )
