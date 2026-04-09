"""
test_docker_arg_validation.py
=============================
Tests for docker_arguments security validation in module configuration.
"""
import json
import os

import pytest
from webinterface.modules import (
    ALLOWED_DOCKER_ARGS,
    check_docker_arguments,
    validate_docker_arguments_change,
    privileged_containers_allowed,
)


# ---------------------------------------------------------------------------
# check_docker_arguments
# ---------------------------------------------------------------------------

class TestCheckDockerArguments:
    def test_empty_string(self):
        assert check_docker_arguments("") == []

    def test_none(self):
        assert check_docker_arguments(None) == []

    def test_invalid_json(self):
        assert check_docker_arguments("not json") == []

    def test_json_non_dict(self):
        assert check_docker_arguments('"just a string"') == []
        assert check_docker_arguments("[1, 2]") == []

    # -- Allowed args --

    def test_allowed_runtime(self):
        assert check_docker_arguments(json.dumps({"runtime": "nvidia"})) == []

    def test_allowed_mem_limit(self):
        assert check_docker_arguments(json.dumps({"mem_limit": "2g"})) == []

    def test_allowed_multiple(self):
        args = json.dumps({"mem_limit": "2g", "cpu_quota": 50000, "pids_limit": 256, "read_only": True})
        assert check_docker_arguments(args) == []

    def test_all_allowed_keys_accepted(self):
        """Every key in ALLOWED_DOCKER_ARGS should pass validation."""
        args = {key: "test" for key in ALLOWED_DOCKER_ARGS}
        assert check_docker_arguments(args) == []

    # -- Disallowed args --

    def test_privileged(self):
        violations = check_docker_arguments(json.dumps({"privileged": True}))
        assert len(violations) == 1
        assert "privileged" in violations[0]

    def test_cap_add(self):
        violations = check_docker_arguments(json.dumps({"cap_add": ["SYS_ADMIN"]}))
        assert len(violations) == 1
        assert "cap_add" in violations[0]

    def test_security_opt(self):
        violations = check_docker_arguments(json.dumps({"security_opt": ["seccomp=unconfined"]}))
        assert len(violations) == 1
        assert "security_opt" in violations[0]

    def test_network_mode(self):
        violations = check_docker_arguments(json.dumps({"network_mode": "host"}))
        assert len(violations) == 1
        assert "network_mode" in violations[0]

    def test_pid_mode(self):
        violations = check_docker_arguments(json.dumps({"pid_mode": "host"}))
        assert len(violations) == 1
        assert "pid_mode" in violations[0]

    def test_devices(self):
        violations = check_docker_arguments(json.dumps({"devices": ["/dev/sda"]}))
        assert len(violations) == 1
        assert "devices" in violations[0]

    def test_cap_drop(self):
        """cap_drop is not in the allowlist — it's managed by mercure itself."""
        violations = check_docker_arguments(json.dumps({"cap_drop": ["ALL"]}))
        assert len(violations) == 1
        assert "cap_drop" in violations[0]

    def test_volumes(self):
        violations = check_docker_arguments(json.dumps({"volumes": {"/host": {"bind": "/c"}}}))
        assert len(violations) == 1
        assert "volumes" in violations[0]

    def test_multiple_disallowed(self):
        args = json.dumps({"privileged": True, "cap_add": ["SYS_ADMIN"], "network_mode": "host"})
        violations = check_docker_arguments(args)
        assert len(violations) == 3

    def test_mixed_allowed_and_disallowed(self):
        args = json.dumps({"mem_limit": "2g", "privileged": True})
        violations = check_docker_arguments(args)
        assert len(violations) == 1
        assert "privileged" in violations[0]

    # -- Dict input (raw config editor path) --

    def test_dict_input_disallowed(self):
        violations = check_docker_arguments({"privileged": True, "security_opt": ["x"]})
        assert len(violations) == 2

    def test_dict_input_allowed(self):
        assert check_docker_arguments({"runtime": "nvidia"}) == []


# ---------------------------------------------------------------------------
# validate_docker_arguments_change
# ---------------------------------------------------------------------------

class TestValidateDockerArgumentsChange:
    def test_no_change_safe(self):
        validate_docker_arguments_change("", "")

    def test_adding_allowed_args(self):
        validate_docker_arguments_change("", json.dumps({"runtime": "nvidia", "mem_limit": "2g"}))

    def test_adding_disallowed_blocked(self):
        with pytest.raises(ValueError, match="privileged"):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))

    def test_adding_cap_add_blocked(self):
        with pytest.raises(ValueError, match="cap_add"):
            validate_docker_arguments_change("", json.dumps({"cap_add": ["SYS_ADMIN"]}))

    def test_adding_security_opt_blocked(self):
        with pytest.raises(ValueError, match="security_opt"):
            validate_docker_arguments_change("", json.dumps({"security_opt": ["seccomp=unconfined"]}))

    def test_keeping_existing_disallowed_ok(self):
        """Existing disallowed args that are unchanged should not be blocked."""
        existing = json.dumps({"privileged": True})
        validate_docker_arguments_change(existing, existing)

    def test_keeping_existing_and_adding_allowed_ok(self):
        old = json.dumps({"privileged": True})
        new = json.dumps({"privileged": True, "runtime": "nvidia"})
        validate_docker_arguments_change(old, new)

    def test_keeping_existing_but_adding_new_disallowed_blocked(self):
        old = json.dumps({"privileged": True})
        new = json.dumps({"privileged": True, "cap_add": ["SYS_ADMIN"]})
        with pytest.raises(ValueError, match="cap_add"):
            validate_docker_arguments_change(old, new)

    def test_removing_disallowed_ok(self):
        old = json.dumps({"privileged": True, "cap_add": ["SYS_ADMIN"]})
        new = json.dumps({"runtime": "nvidia"})
        validate_docker_arguments_change(old, new)

    def test_env_var_bypass(self, monkeypatch):
        """MERCURE_ALLOW_PRIVILEGED_CONTAINERS bypasses all checks."""
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "true")
        validate_docker_arguments_change("", json.dumps({"privileged": True, "cap_add": ["SYS_ADMIN"]}))

    def test_env_var_bypass_values(self, monkeypatch):
        for val in ("1", "True", "YES", "true"):
            monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", val)
            validate_docker_arguments_change("", json.dumps({"privileged": True}))

    def test_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", raising=False)
        with pytest.raises(ValueError):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))

    def test_env_var_false_does_not_bypass(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "false")
        with pytest.raises(ValueError):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))


# ---------------------------------------------------------------------------
# privileged_containers_allowed
# ---------------------------------------------------------------------------

class TestPrivilegedContainersAllowed:
    def test_not_set(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", raising=False)
        assert privileged_containers_allowed() is False

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "")
        assert privileged_containers_allowed() is False

    def test_true(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "true")
        assert privileged_containers_allowed() is True

    def test_one(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "1")
        assert privileged_containers_allowed() is True

    def test_yes(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "yes")
        assert privileged_containers_allowed() is True

    def test_no(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "no")
        assert privileged_containers_allowed() is False


# ---------------------------------------------------------------------------
# Web UI integration: module save endpoint
# ---------------------------------------------------------------------------

class TestModuleSaveEndpoint:
    def test_save_module_blocks_disallowed(self, test_client, mercure_config):
        mercure_config()
        response = test_client.post(
            "/modules/edit/test_module",
            data={
                "docker_tag": "alpine:3.11",
                "docker_arguments": json.dumps({"privileged": True}),
                "additional_volumes": "{}",
                "environment": "{}",
                "settings": "{}",
                "contact": "",
                "comment": "",
                "constraints": "",
                "resources": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "privileged" in response.text

    def test_save_module_allows_safe_args(self, test_client, mercure_config):
        mercure_config()
        response = test_client.post(
            "/modules/edit/test_module",
            data={
                "docker_tag": "alpine:3.11",
                "docker_arguments": json.dumps({"runtime": "nvidia", "mem_limit": "4g"}),
                "additional_volumes": "{}",
                "environment": "{}",
                "settings": "{}",
                "contact": "",
                "comment": "",
                "constraints": "",
                "resources": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert response.headers.get("hx-redirect") == "/modules/"

    def test_save_module_preserves_existing_disallowed(self, test_client, mercure_config):
        """If module already has disallowed args, saving without change should work."""
        import common.config as config
        mercure_config({"modules": {
            "test_module": {
                "docker_tag": "alpine:3.11",
                "docker_arguments": json.dumps({"privileged": True}),
            }
        }})
        config.read_config()

        response = test_client.post(
            "/modules/edit/test_module",
            data={
                "docker_tag": "alpine:3.11",
                "docker_arguments": json.dumps({"privileged": True}),
                "additional_volumes": "{}",
                "environment": "{}",
                "settings": "{}",
                "contact": "",
                "comment": "",
                "constraints": "",
                "resources": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert response.headers.get("hx-redirect") == "/modules/"


# ---------------------------------------------------------------------------
# Web UI integration: raw config editor endpoint
# ---------------------------------------------------------------------------

class TestConfigEditorEndpoint:
    def test_config_editor_blocks_disallowed(self, test_client, mercure_config):
        import common.config as config
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["docker_arguments"] = json.dumps({"privileged": True})

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Blocked" in response.text
        assert "privileged" in response.text

    def test_config_editor_allows_safe_change(self, test_client, mercure_config):
        import common.config as config
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["docker_arguments"] = json.dumps({"runtime": "nvidia"})

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_config_editor_preserves_existing_disallowed(self, test_client, mercure_config):
        import common.config as config
        dangerous_args = json.dumps({"privileged": True})
        mercure_config({"modules": {
            "test_module": {
                "docker_tag": "alpine:3.11",
                "docker_arguments": dangerous_args,
            }
        }})
        config.read_config()

        new_config = config.mercure.dict()
        assert new_config["modules"]["test_module"]["docker_arguments"] == dangerous_args

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_config_editor_blocks_adding_new_disallowed(self, test_client, mercure_config):
        import common.config as config
        mercure_config({"modules": {
            "test_module": {
                "docker_tag": "alpine:3.11",
                "docker_arguments": json.dumps({"privileged": True}),
            }
        }})
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["docker_arguments"] = json.dumps({
            "privileged": True,
            "cap_add": ["SYS_ADMIN"],
        })

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "cap_add" in response.text

    def test_config_editor_blocks_new_module_with_disallowed(self, test_client, mercure_config):
        import common.config as config
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["evil_module"] = {
            "docker_tag": "evil:latest",
            "docker_arguments": json.dumps({"network_mode": "host"}),
        }

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "evil_module" in response.text
        assert "network_mode" in response.text

    def test_config_editor_env_var_bypass(self, test_client, mercure_config, monkeypatch):
        import common.config as config
        monkeypatch.setenv("MERCURE_ALLOW_PRIVILEGED_CONTAINERS", "true")
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["docker_arguments"] = json.dumps({"privileged": True})

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 303
