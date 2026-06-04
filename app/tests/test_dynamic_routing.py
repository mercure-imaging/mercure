"""
test_dynamic_routing.py
=======================
Tests for dynamic routing feature: processing modules can override dispatch targets
via __mercure_routing in result.json.
"""
import json
import shutil
import uuid
from pathlib import Path
from typing import Callable, Dict
from unittest.mock import MagicMock

import docker.errors
import pytest
from common import config
from common.types import Config, Module, Rule
from process import processor
from pytest_mock import MockerFixture
from routing import router

from .testing_common import FakeDockerContainer, mock_incoming_uid, mock_task_ids

logger = config.get_logger()


def make_fake_processor_with_routing(fs, mocked, routing_directive):
    """Create a fake processor that writes __mercure_routing into result.json."""

    def fake_processor(tag, *, environment=None, volumes=None, mounts=[], **kwargs):
        if "cat" in kwargs.get("command", ""):
            raise docker.errors.ContainerError(None, None, None, None, None)
        if tag == "busybox:stable-musl":
            return mocked.DEFAULT
        if not mounts:
            raise Exception("No volume specified")
        in_ = Path(next(m for m in mounts if m["Target"] == "/tmp/data")['Source'])
        out_ = Path(next(m for m in mounts if m["Target"] == "/tmp/output")['Source'])

        for child in in_.iterdir():
            shutil.copy(child, out_ / child.name)

        result = {"analysis_result": "some_value"}
        if routing_directive is not None:
            result["__mercure_routing"] = routing_directive
        fs.create_file(out_ / "result.json", contents=json.dumps(result))
        return mocked.DEFAULT
    return fake_processor


def setup_docker_mocks(mocked, fake_processor_side_effect):
    """Mock docker.from_env() to return a fake client with our processor."""
    fake_container = FakeDockerContainer()
    mock_client = MagicMock()
    mock_client.containers.run = MagicMock(return_value=fake_container, side_effect=fake_processor_side_effect)
    mock_client.images.pull = MagicMock(return_value=None)
    mock_client.images.prune = MagicMock(return_value=None)
    mocked.patch("process.process_series.docker.from_env", return_value=mock_client)


def create_and_route(fs, mocked, task_id, config, uid="TESTFAKEUID"):
    """Route a series through the router, placing it in the processing folder."""
    new_task_id = "new-task-" + str(uuid.uuid1())
    mock_incoming_uid(config, fs, uid)
    mock_task_ids(mocked, task_id, new_task_id)
    router.run_router()


# --- Test: Dynamic routing overrides dispatch target ---

@pytest.mark.asyncio
async def test_dynamic_routing_overrides_target(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    """When dynamic_routing is enabled and module outputs __mercure_routing with a valid target,
    the task should be dispatched to that target instead of the statically configured one."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module outputs __mercure_routing directing to test_target
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "test_target"}))
    await processor.run_processor()

    # The task should end up in the outgoing folder (for dispatch), not success
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1, f"Expected 1 task in outgoing, found {len(outgoing_tasks)}"

    # Read the task file and verify the dispatch target was overridden
    task_file = outgoing_tasks[0] / "task.json"
    assert task_file.exists()
    with open(task_file) as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["test_target"]
    assert "test_target" in task_data["dispatch"]["status"]
    assert task_data["dispatch"]["status"]["test_target"]["state"] == "waiting"


# --- Test: Dynamic routing with multiple targets ---

@pytest.mark.asyncio
async def test_dynamic_routing_multiple_targets(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    """Module can request routing to multiple targets."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    setup_docker_mocks(mocked, make_fake_processor_with_routing(
        fs, mocked, {"target": ["test_target", "dummy"]}
    ))
    await processor.run_processor()

    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert set(task_data["dispatch"]["target_name"]) == {"test_target", "dummy"}


# --- Test: Dynamic routing discard directive ---

@pytest.mark.asyncio
async def test_dynamic_routing_discard(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    """When module requests discard via __mercure_routing, task goes to success (not dispatched)."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"discard": True}))
    await processor.run_processor()

    # Should go to success folder (not outgoing, not error)
    assert list(Path("/var/outgoing").iterdir()) == []
    success_tasks = list(Path("/var/success").iterdir())
    assert len(success_tasks) == 1


# --- Test: Dynamic routing disabled on rule (directive ignored) ---

@pytest.mark.asyncio
async def test_dynamic_routing_disabled_on_rule(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    """When dynamic_routing is not enabled on the rule, __mercure_routing is ignored
    and the static target is used."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=False,  # disabled
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module tries to route to test_target, but dynamic_routing is disabled
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "test_target"}))
    await processor.run_processor()

    # Should still dispatch to the original target (dummy)
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["dummy"]


# --- Test: Dynamic routing with allowed_targets whitelist ---

@pytest.mark.asyncio
async def test_dynamic_routing_allowed_targets_whitelist(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """When dynamic_routing_allowed_targets is set, only those targets are permitted.
    Invalid targets fall back to static target."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
                dynamic_routing_allowed_targets=["test_target", "dummy"],
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module requests a target NOT in the whitelist
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "sftp_target"}))
    await processor.run_processor()

    # Should fall back to original target (dummy) since sftp_target is not in allowed list
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["dummy"]


# --- Test: Dynamic routing with allowed target (passes whitelist) ---

@pytest.mark.asyncio
async def test_dynamic_routing_allowed_targets_passes(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """When module requests a target that IS in the whitelist, it succeeds."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
                dynamic_routing_allowed_targets=["test_target", "dummy"],
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "test_target"}))
    await processor.run_processor()

    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["test_target"]


# --- Test: Dynamic routing with nonexistent target falls back ---

@pytest.mark.asyncio
async def test_dynamic_routing_nonexistent_target_fallback(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """When module requests a target that doesn't exist in mercure config,
    falls back to static target."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module requests a target that doesn't exist
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "nonexistent_target"}))
    await processor.run_processor()

    # Should fall back to original target (dummy)
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["dummy"]


# --- Test: No __mercure_routing in result.json (unchanged behavior) ---

@pytest.mark.asyncio
async def test_no_dynamic_routing_directive_unchanged(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """When module doesn't write __mercure_routing, dispatch proceeds with static target."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="both",
                target="dummy",
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module writes result.json WITHOUT __mercure_routing
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, None))
    await processor.run_processor()

    # Should dispatch to original target (dummy)
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["dummy"]


# --- Test: Dynamic routing adds dispatch to process-only rule ---

@pytest.mark.asyncio
async def test_dynamic_routing_adds_dispatch_to_process_only(
    fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture
):
    """When a process-only rule has dynamic_routing enabled and module requests a target,
    dispatching is added even though the rule action is 'process' (not 'both')."""
    partial = {
        "modules": {
            "classifier_module": Module(docker_tag="busybox:stable", settings={}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action="process",  # process only, no static target
                action_trigger="series",
                study_trigger_condition="timeout",
                processing_module="classifier_module",
                dynamic_routing=True,
            ).dict()
        },
    }
    config = mercure_config({"process_runner": "docker", **partial})

    task_id = str(uuid.uuid1())
    create_and_route(fs, mocked, task_id, config)

    # Module requests routing to test_target
    setup_docker_mocks(mocked, make_fake_processor_with_routing(fs, mocked, {"target": "test_target"}))
    await processor.run_processor()

    # Should end up in outgoing (dispatched) even though rule was process-only
    outgoing_tasks = list(Path("/var/outgoing").iterdir())
    assert len(outgoing_tasks) == 1

    with open(outgoing_tasks[0] / "task.json") as f:
        task_data = json.load(f)

    assert task_data["dispatch"]["target_name"] == ["test_target"]
    assert task_data["dispatch"]["status"]["test_target"]["state"] == "waiting"
