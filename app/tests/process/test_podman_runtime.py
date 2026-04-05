"""
test_podman_runtime.py
======================
Tests for PodmanRuntime, get_runtime() factory, and Podman-based
end-to-end processing.
"""

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, PropertyMock, call

import pytest
from podman.errors import APIError, ContainerError, ImageNotFound

import common
import common.config as config
import common.monitor
from common.types import Module, Rule
from process.podman_runtime import PodmanRuntime
from process.runtime_base import get_runtime


# ------------------------------------------------------------------ #
# Fake Podman infrastructure                                           #
# ------------------------------------------------------------------ #

class FakePodmanContainer:
    """Minimal fake of a podman-py Container object."""

    def __init__(self, exit_code: int = 0, log_output: bytes = b"Log output"):
        self._exit_code = exit_code
        self._log_output = log_output

    def wait(self, timeout=None):
        return {"StatusCode": self._exit_code}

    def logs(self, timestamps=False):
        return self._log_output

    def remove(self):
        pass


class FakePodmanImage:
    def __init__(self, tags: List[str], digests: Optional[List[str]] = None):
        self.tags = tags
        self.attrs = {"RepoDigests": digests or []}


def make_fake_podman_run(fs, mocked, fails: bool = False):
    """
    Return a callable that mimics podman client.containers.run().

    When called for MONAI detection (command contains 'cat') it raises
    ContainerError so the runtime falls through to normal execution.
    When called for the actual processing step it copies files from in/
    to out/ (and writes result.json) so process_series can complete.
    """
    def _fake_run(tag, *, command=None, entrypoint=None, volumes=None,
                  environment=None, detach=False, **kwargs):
        # MONAI detection probe
        if command and "cat" in command:
            raise ContainerError(
                container=MagicMock(), exit_status=1,
                command=command, image=tag, stderr=b""
            )

        # Real processing run
        if not volumes:
            raise Exception("No volumes specified")

        in_bind  = next(p for p, cfg in volumes.items() if cfg["bind"] == "/tmp/data")
        out_bind = next(p for p, cfg in volumes.items() if cfg["bind"] == "/tmp/output")
        in_  = Path(in_bind)
        out_ = Path(out_bind)

        for child in in_.iterdir():
            shutil.copy(child, out_ / child.name)

        # Write result.json if the module settings contain a "result" key
        try:
            with (in_ / "task.json").open() as fp:
                result = json.load(fp)["process"]["settings"].get("result", {})
            fs.create_file(out_ / "result.json", contents=json.dumps(result))
        except Exception:
            pass

        if fails:
            raise Exception("fake failure")

        return FakePodmanContainer()

    return _fake_run


def make_fake_podman_client(fs, mocked, fails: bool = False,
                             local_images: Optional[List[FakePodmanImage]] = None):
    """Build a MagicMock Podman client wired up for testing."""
    client = MagicMock()
    client.containers.run.side_effect = make_fake_podman_run(fs, mocked, fails)
    client.images.pull.return_value = FakePodmanImage(
        tags=["docker.io/library/busybox:stable"],
        digests=["docker.io/library/busybox:stable@sha256:abc"],
    )
    client.images.prune.return_value = None
    if local_images is not None:
        client.images.list.return_value = local_images
    return client


# ------------------------------------------------------------------ #
# _qualify_image (pure function)                                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tag,expected", [
    # Official Docker Hub library images
    ("ubuntu:22.04",            "docker.io/library/ubuntu:22.04"),
    ("ubuntu",                  "docker.io/library/ubuntu"),
    ("busybox:stable",          "docker.io/library/busybox:stable"),
    # Org-scoped Docker Hub images
    ("myorg/myimage:latest",    "docker.io/myorg/myimage:latest"),
    ("myorg/myimage",           "docker.io/myorg/myimage"),
    # Already-qualified names are left unchanged
    ("docker.io/myorg/img",     "docker.io/myorg/img"),
    ("quay.io/biocontainers/x", "quay.io/biocontainers/x"),
    ("ghcr.io/owner/img:tag",   "ghcr.io/owner/img:tag"),
    ("localhost/myimage",       "localhost/myimage"),
    # Registry with port: the colon in the first segment means it's a host:port
    ("registry.example.com:5000/myimage", "registry.example.com:5000/myimage"),
    # Digest variants
    ("ubuntu@sha256:abc",           "docker.io/library/ubuntu@sha256:abc"),
    ("myorg/img@sha256:abc",        "docker.io/myorg/img@sha256:abc"),
    ("docker.io/lib/img@sha256:x",  "docker.io/lib/img@sha256:x"),
])
def test_qualify_image(tag, expected):
    assert PodmanRuntime._qualify_image(tag) == expected


# ------------------------------------------------------------------ #
# get_runtime() factory                                                #
# ------------------------------------------------------------------ #

def test_get_runtime_podman_via_config(fs, mercure_config, monkeypatch):
    """process_runner='podman' + systemd env → PodmanRuntime."""
    monkeypatch.setenv("MERCURE_RUNNER", "systemd")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    mercure_config({"process_runner": "podman"})
    assert isinstance(get_runtime(), PodmanRuntime)


def test_get_runtime_podman_via_env(fs, mercure_config, monkeypatch):
    """MERCURE_RUNNER='podman' → PodmanRuntime regardless of config."""
    monkeypatch.setenv("MERCURE_RUNNER", "podman")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    mercure_config({})
    assert isinstance(get_runtime(), PodmanRuntime)


def test_get_runtime_podman_blocked_inside_docker(fs, mercure_config, monkeypatch):
    """process_runner='podman' + MERCURE_RUNNER='docker' without CONTAINER_HOST raises."""
    monkeypatch.setenv("MERCURE_RUNNER", "docker")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    mercure_config({"process_runner": "podman"})
    with pytest.raises(Exception, match="CONTAINER_HOST"):
        get_runtime()


def test_get_runtime_podman_allowed_inside_docker_with_socket(fs, mercure_config, monkeypatch):
    """process_runner='podman' + MERCURE_RUNNER='docker' + CONTAINER_HOST set → PodmanRuntime."""
    monkeypatch.setenv("MERCURE_RUNNER", "docker")
    monkeypatch.setenv("CONTAINER_HOST", "unix:///run/podman/podman.sock")
    mercure_config({"process_runner": "podman"})
    assert isinstance(get_runtime(), PodmanRuntime)


def test_get_runtime_docker_default(fs, mercure_config, monkeypatch):
    """MERCURE_RUNNER='docker' + process_runner='' → DockerRuntime."""
    from process.docker_runtime import DockerRuntime
    monkeypatch.setenv("MERCURE_RUNNER", "docker")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    mercure_config({"process_runner": ""})
    assert isinstance(get_runtime(), DockerRuntime)


# ------------------------------------------------------------------ #
# _detect_monai                                                        #
# ------------------------------------------------------------------ #

def test_detect_monai_returns_none_for_normal_image(mocked, monkeypatch):
    """Images without a MONAI manifest raise ContainerError → _detect_monai returns None."""
    runtime = PodmanRuntime()
    client = MagicMock()
    client.containers.run.side_effect = ContainerError(
        container=MagicMock(), exit_status=1,
        command="cat /etc/monai/app.json", image="busybox", stderr=b""
    )
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime._detect_monai("busybox:stable") is None


def test_detect_monai_parses_manifest(mocked, monkeypatch):
    """Images with a MONAI manifest return the command list."""
    manifest = json.dumps({"command": ["python", "-m", "myapp"]}).encode()
    runtime = PodmanRuntime()
    client = MagicMock()
    client.containers.run.return_value = manifest
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime._detect_monai("monai/map:latest") == ["python", "-m", "myapp"]


def test_detect_monai_parses_string_command(mocked, monkeypatch):
    """String 'command' in the manifest is split into a list."""
    manifest = json.dumps({"command": "python -m myapp"}).encode()
    runtime = PodmanRuntime()
    client = MagicMock()
    client.containers.run.return_value = manifest
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime._detect_monai("monai/map:latest") == ["python", "-m", "myapp"]


def test_detect_monai_raises_on_missing_image(mocked, monkeypatch):
    """ImageNotFound in _detect_monai propagates as an exception."""
    runtime = PodmanRuntime()
    client = MagicMock()
    client.containers.run.side_effect = ImageNotFound("docker.io/library/missing:latest")
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    with pytest.raises(Exception, match="not found"):
        runtime._detect_monai("missing:latest")


# ------------------------------------------------------------------ #
# list_local_images                                                    #
# ------------------------------------------------------------------ #

def test_list_local_images_returns_sorted_tags(mocked, monkeypatch):
    fake_images = [
        FakePodmanImage(["docker.io/library/zz:latest"]),
        FakePodmanImage(["docker.io/library/aa:latest"]),
        FakePodmanImage([]),  # image with no tags, should be skipped
        FakePodmanImage(["docker.io/library/mm:v1"]),
    ]
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.list.return_value = fake_images
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    result = runtime.list_local_images()
    assert result == [
        "docker.io/library/aa:latest",
        "docker.io/library/mm:v1",
        "docker.io/library/zz:latest",
    ]


def test_list_local_images_returns_none_on_error(mocked, monkeypatch):
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.list.side_effect = APIError("connection refused")
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime.list_local_images() is None


# ------------------------------------------------------------------ #
# validate_image                                                       #
# ------------------------------------------------------------------ #

def test_validate_image_present_locally(mocked, monkeypatch):
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.get.return_value = FakePodmanImage(["docker.io/library/ubuntu:22.04"])
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime.validate_image("ubuntu:22.04") is None


def test_validate_image_pulls_from_registry(mocked, monkeypatch):
    """Image not local but pullable → None (no error)."""
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("ubuntu:22.04")
    client.images.pull.return_value = FakePodmanImage(["docker.io/library/ubuntu:22.04"])
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    assert runtime.validate_image("ubuntu:22.04") is None


def test_validate_image_not_found(mocked, monkeypatch):
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("nonexistent:latest")
    err = APIError("not found")
    client.images.pull.side_effect = err
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    result = runtime.validate_image("nonexistent:latest")
    assert result is not None
    assert "not found" in result.lower()


def test_validate_image_unauthorized(mocked, monkeypatch):
    runtime = PodmanRuntime()
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("private/image:latest")
    client.images.pull.side_effect = APIError("unauthorized access denied")
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )
    result = runtime.validate_image("private/image:latest")
    assert result is not None
    assert "denied" in result.lower() or "credentials" in result.lower()


def test_validate_image_connection_error(mocked, monkeypatch):
    """Failing to connect to the socket produces a human-readable error."""
    def _raise_connection_error(self):
        raise ConnectionError("no socket")

    monkeypatch.setattr(PodmanRuntime, "_podman_client", property(_raise_connection_error))
    runtime = PodmanRuntime()
    result = runtime.validate_image("ubuntu:22.04")
    assert result is not None
    assert "podman" in result.lower() or "socket" in result.lower() or "connect" in result.lower()


# ------------------------------------------------------------------ #
# SELinux volume labels                                                #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_execute_uses_private_selinux_for_job_dirs(fs, mercure_config, mocked, monkeypatch):
    """in/ and out/ dirs get ,Z (private) SELinux label."""
    monkeypatch.setenv("MERCURE_RUNNER", "systemd")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("MERCURE_HOST_DATA_PATH", raising=False)

    cfg = mercure_config({"process_runner": "podman"})
    folder = Path(cfg.processing_folder) / str(uuid.uuid1())
    fs.create_dir(folder / "in")
    fs.create_dir(folder / "out")
    (folder / "in").chmod(0o777)
    (folder / "out").chmod(0o777)

    module = Module(docker_tag="busybox:stable")

    captured_volumes: Dict = {}
    container = FakePodmanContainer()

    def _fake_run(tag, *, command=None, volumes=None, **kwargs):
        if command and "cat" in command:
            raise ContainerError(
                container=MagicMock(), exit_status=1,
                command=command, image=tag, stderr=b""
            )
        captured_volumes.update(volumes or {})
        return container

    client = MagicMock()
    client.containers.run.side_effect = _fake_run
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )

    runtime = PodmanRuntime()
    await runtime._execute(
        tag="busybox:stable",
        folder=folder,
        container_in_dir="/tmp/data",
        container_out_dir="/tmp/output",
        environment={},
        additional_volumes={},
        arguments={},
        monai_command=None,
        module=module,
        persistence_mount=None,
    )

    in_mode  = captured_volumes[str(folder / "in")]["mode"]
    out_mode = captured_volumes[str(folder / "out")]["mode"]
    assert ",Z" in in_mode,  f"Expected private label ,Z in in/ mode: {in_mode}"
    assert ",Z" in out_mode, f"Expected private label ,Z in out/ mode: {out_mode}"


@pytest.mark.asyncio
async def test_execute_uses_shared_selinux_for_persistence(fs, mercure_config, mocked, monkeypatch):
    """The persistence folder gets ,z (shared) SELinux label."""
    monkeypatch.setenv("MERCURE_RUNNER", "systemd")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("MERCURE_HOST_DATA_PATH", raising=False)

    cfg = mercure_config({"process_runner": "podman"})
    folder = Path(cfg.processing_folder) / str(uuid.uuid1())
    fs.create_dir(folder / "in")
    fs.create_dir(folder / "out")
    (folder / "in").chmod(0o777)
    (folder / "out").chmod(0o777)

    persistence_src = "/var/persistence/mymodule"
    fs.create_dir(persistence_src)

    module = Module(docker_tag="busybox:stable")
    captured_volumes: Dict = {}
    container = FakePodmanContainer()

    def _fake_run(tag, *, command=None, volumes=None, **kwargs):
        if command and "cat" in command:
            raise ContainerError(
                container=MagicMock(), exit_status=1,
                command=command, image=tag, stderr=b""
            )
        captured_volumes.update(volumes or {})
        return container

    client = MagicMock()
    client.containers.run.side_effect = _fake_run
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )

    runtime = PodmanRuntime()
    await runtime._execute(
        tag="busybox:stable",
        folder=folder,
        container_in_dir="/tmp/data",
        container_out_dir="/tmp/output",
        environment={},
        additional_volumes={},
        arguments={},
        monai_command=None,
        module=module,
        persistence_mount=(persistence_src, "/tmp/persistence"),
    )

    p_mode = captured_volumes[persistence_src]["mode"]
    assert ",z" in p_mode and ",Z" not in p_mode, (
        f"Expected shared label ,z (not ,Z) for persistence: {p_mode}"
    )


# ------------------------------------------------------------------ #
# Full process_series integration with Podman                          #
# ------------------------------------------------------------------ #

_config_partial: Dict[str, Any] = {
    "modules": {
        "test_module": Module(docker_tag="busybox:stable", settings={"fizz": "buzz"}).dict(),
    },
    "rules": {
        "catchall": Rule(
            rule="True",
            action="process",
            action_trigger="series",
            study_trigger_condition="timeout",
            processing_module="test_module",
        ).dict()
    },
}


@pytest.mark.asyncio
async def test_process_series_podman(
    fs, mercure_config, mocked, monkeypatch,
):
    """End-to-end: process_series routes and processes a series via PodmanRuntime."""
    from process import processor
    from tests.testing_common import mock_incoming_uid, mock_task_ids
    import routing.generate_taskfile
    from routing import router

    monkeypatch.setenv("MERCURE_RUNNER", "systemd")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("MERCURE_HOST_DATA_PATH", raising=False)

    cfg = mercure_config({"process_runner": "podman", **_config_partial})

    task_id = str(uuid.uuid1())
    new_task_id = "new-task-" + str(uuid.uuid1())

    mock_incoming_uid(cfg, fs, "TESTFAKEUID")
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    processor_path = next(Path("/var/processing").iterdir())

    client = make_fake_podman_client(fs, mocked)
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )

    await processor.run_processor()

    # Container should have been invoked: once for MONAI detection, once for processing
    assert client.containers.run.call_count == 2

    # Task folder moved to success
    assert (Path("/var/success") / processor_path.name).exists()
    assert not list(Path("/var/processing").glob("**/*"))

    # Monitor events (attach_spies wraps common.monitor.* as spies on the module)
    from common.monitor import task_event
    common.monitor.async_send_task_event.assert_any_call(  # type: ignore
        task_event.PROCESS_BEGIN, new_task_id, 1, "test_module", "Processing job running"
    )


@pytest.mark.asyncio
async def test_process_series_podman_failure(
    fs, mercure_config, mocked, monkeypatch,
):
    """A non-zero container exit code moves the task to the error folder."""
    from process import processor
    from tests.testing_common import mock_incoming_uid, mock_task_ids
    from routing import router

    monkeypatch.setenv("MERCURE_RUNNER", "systemd")
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("MERCURE_HOST_DATA_PATH", raising=False)

    cfg = mercure_config({"process_runner": "podman", **_config_partial})

    task_id = str(uuid.uuid1())
    new_task_id = "new-task-" + str(uuid.uuid1())

    mock_incoming_uid(cfg, fs, "TESTFAKEUID")
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()

    processor_path = next(Path("/var/processing").iterdir())

    # Container exits with code 1
    def _failing_run(tag, *, command=None, volumes=None, **kwargs):
        if command and "cat" in command:
            raise ContainerError(
                container=MagicMock(), exit_status=1,
                command=command, image=tag, stderr=b""
            )
        in_ = Path(next(p for p, c in volumes.items() if c["bind"] == "/tmp/data"))
        out_ = Path(next(p for p, c in volumes.items() if c["bind"] == "/tmp/output"))
        for child in in_.iterdir():
            shutil.copy(child, out_ / child.name)
        return FakePodmanContainer(exit_code=1)

    client = MagicMock()
    client.containers.run.side_effect = _failing_run
    client.images.pull.return_value = FakePodmanImage(["docker.io/library/busybox:stable"])
    client.images.prune.return_value = None
    monkeypatch.setattr(
        PodmanRuntime, "_podman_client", property(lambda self: client)
    )

    await processor.run_processor()

    assert (Path("/var/error") / processor_path.name).exists()
    assert not list(Path("/var/processing").glob("**/*"))
