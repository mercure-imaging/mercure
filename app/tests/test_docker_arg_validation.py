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
    allow_unsafe_docker_args,
    forbid_unsafe_docker_args,
    check_volumes,
    validate_volumes_change,
    get_allowed_volume_bases,
    allow_unsafe_volumes,
    forbid_unsafe_volumes,
    DEFAULT_VOLUME_BASE,
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
        """MERCURE_ALLOW_UNSAFE_DOCKER_ARGS bypasses all checks."""
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "true")
        validate_docker_arguments_change("", json.dumps({"privileged": True, "cap_add": ["SYS_ADMIN"]}))

    def test_env_var_bypass_values(self, monkeypatch):
        for val in ("1", "True", "YES", "true"):
            monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", val)
            validate_docker_arguments_change("", json.dumps({"privileged": True}))

    def test_env_var_not_set(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", raising=False)
        with pytest.raises(ValueError):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))

    def test_env_var_false_does_not_bypass(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "false")
        with pytest.raises(ValueError):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))


# ---------------------------------------------------------------------------
# allow_unsafe_docker_args
# ---------------------------------------------------------------------------

class TestAllowUnsafeDockerArgs:
    def test_not_set(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", raising=False)
        assert allow_unsafe_docker_args() is False

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "")
        assert allow_unsafe_docker_args() is False

    def test_false(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "false")
        assert allow_unsafe_docker_args() is False

    def test_arbitrary_truthy(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "anything")
        assert allow_unsafe_docker_args() is True


# ---------------------------------------------------------------------------
# FORBID overrides ALLOW (docker args)
# ---------------------------------------------------------------------------

class TestForbidOverridesAllowDockerArgs:
    def test_both_set_forbid_wins(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "true")
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_DOCKER_ARGS", "true")
        assert allow_unsafe_docker_args() is False
        assert forbid_unsafe_docker_args() is True

    def test_allow_only(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "true")
        monkeypatch.delenv("MERCURE_FORBID_UNSAFE_DOCKER_ARGS", raising=False)
        assert allow_unsafe_docker_args() is True

    def test_forbid_only(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", raising=False)
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_DOCKER_ARGS", "true")
        assert allow_unsafe_docker_args() is False

    def test_validate_blocked_when_both_set(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "true")
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_DOCKER_ARGS", "true")
        with pytest.raises(ValueError):
            validate_docker_arguments_change("", json.dumps({"privileged": True}))


# ---------------------------------------------------------------------------
# check_volumes
# ---------------------------------------------------------------------------

class TestCheckVolumes:
    def test_empty(self):
        assert check_volumes("") == []

    def test_none(self):
        assert check_volumes(None) == []

    def test_invalid_json(self):
        assert check_volumes("not json") == []

    def test_json_non_dict(self):
        assert check_volumes("[1, 2]") == []

    def test_allowed_path(self):
        vols = json.dumps({f"{DEFAULT_VOLUME_BASE}/data": {"bind": "/data", "mode": "ro"}})
        assert check_volumes(vols) == []

    def test_allowed_path_exact(self):
        vols = json.dumps({DEFAULT_VOLUME_BASE: {"bind": "/data", "mode": "ro"}})
        assert check_volumes(vols) == []

    def test_disallowed_path(self):
        vols = json.dumps({"/etc/shadow": {"bind": "/data", "mode": "ro"}})
        violations = check_volumes(vols)
        assert len(violations) == 1
        assert "/etc/shadow" in violations[0]

    def test_multiple_mixed(self):
        vols = json.dumps({
            f"{DEFAULT_VOLUME_BASE}/ok": {"bind": "/a"},
            "/etc/passwd": {"bind": "/b"},
            "/root": {"bind": "/c"},
        })
        violations = check_volumes(vols)
        assert len(violations) == 2

    def test_dict_input(self):
        assert check_volumes({f"{DEFAULT_VOLUME_BASE}/x": {"bind": "/x"}}) == []
        violations = check_volumes({"/tmp/evil": {"bind": "/x"}})
        assert len(violations) == 1

    def test_extra_volumes_env_single(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/custom/path")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        assert check_volumes(json.dumps({"/custom/path/sub": {"bind": "/x"}})) == []
        assert len(check_volumes(json.dumps({"/other": {"bind": "/x"}}))) == 1

    def test_extra_volumes_env_multiple(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/data/models;/data/configs;/scratch")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        # Allowed: under any of the extra paths or the default base
        assert check_volumes(json.dumps({"/data/models/brain": {"bind": "/m"}})) == []
        assert check_volumes(json.dumps({"/data/configs": {"bind": "/c"}})) == []
        assert check_volumes(json.dumps({"/scratch/tmp": {"bind": "/t"}})) == []
        assert check_volumes(json.dumps({f"{DEFAULT_VOLUME_BASE}/x": {"bind": "/x"}})) == []
        # Disallowed: not under any allowed base
        assert len(check_volumes(json.dumps({"/etc/passwd": {"bind": "/p"}}))) == 1
        assert len(check_volumes(json.dumps({"/data": {"bind": "/d"}}))) == 1

    def test_extra_volumes_env_with_spaces(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", " /foo ; /bar ")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        assert check_volumes(json.dumps({"/foo/sub": {"bind": "/x"}})) == []
        assert check_volumes(json.dumps({"/bar/sub": {"bind": "/x"}})) == []

    def test_allow_unsafe_volumes_bypasses(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        assert check_volumes(json.dumps({"/etc/shadow": {"bind": "/x"}})) == []


# ---------------------------------------------------------------------------
# get_allowed_volume_bases
# ---------------------------------------------------------------------------

class TestGetAllowedVolumeBases:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", raising=False)
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        bases = get_allowed_volume_bases()
        assert bases == [DEFAULT_VOLUME_BASE]

    def test_extra_paths(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/foo;/bar")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        bases = get_allowed_volume_bases()
        assert DEFAULT_VOLUME_BASE in bases
        assert "/foo" in bases
        assert "/bar" in bases

    def test_extra_paths_with_spaces(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", " /foo ; /bar ; ")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        bases = get_allowed_volume_bases()
        assert "/foo" in bases
        assert "/bar" in bases
        assert "" not in bases

    def test_extra_paths_empty_segments_ignored(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/foo;;/bar")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        bases = get_allowed_volume_bases()
        assert len(bases) == 3  # default + /foo + /bar

    def test_allow_unsafe_returns_none(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        assert get_allowed_volume_bases() is None

    def test_allow_unsafe_overrides_extra(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "1")
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/foo")
        assert get_allowed_volume_bases() is None


# ---------------------------------------------------------------------------
# validate_volumes_change
# ---------------------------------------------------------------------------

class TestValidateVolumesChange:
    def test_no_change(self):
        validate_volumes_change("", "")

    def test_adding_allowed(self):
        validate_volumes_change("", json.dumps({f"{DEFAULT_VOLUME_BASE}/x": {"bind": "/x"}}))

    def test_adding_disallowed_blocked(self):
        with pytest.raises(ValueError, match="/etc"):
            validate_volumes_change("", json.dumps({"/etc/shadow": {"bind": "/x"}}))

    def test_keeping_existing_disallowed_ok(self):
        existing = json.dumps({"/etc/shadow": {"bind": "/x"}})
        validate_volumes_change(existing, existing)

    def test_removing_disallowed_ok(self):
        old = json.dumps({"/etc/shadow": {"bind": "/x"}})
        validate_volumes_change(old, "{}")

    def test_allow_unsafe_bypasses(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        validate_volumes_change("", json.dumps({"/etc/shadow": {"bind": "/x"}}))

    def test_extra_volumes_allows_configured_paths(self, monkeypatch):
        monkeypatch.setenv("MERCURE_PROCESSOR_EXTRA_VOLUMES", "/data/models;/data/configs")
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        validate_volumes_change("", json.dumps({"/data/models/brain": {"bind": "/m"}}))
        validate_volumes_change("", json.dumps({"/data/configs/x": {"bind": "/c"}}))
        with pytest.raises(ValueError):
            validate_volumes_change("", json.dumps({"/etc/passwd": {"bind": "/p"}}))


# ---------------------------------------------------------------------------
# allow_unsafe_volumes / forbid_unsafe_volumes
# ---------------------------------------------------------------------------

class TestAllowUnsafeVolumes:
    def test_not_set(self, monkeypatch):
        monkeypatch.delenv("MERCURE_ALLOW_UNSAFE_VOLUMES", raising=False)
        monkeypatch.delenv("MERCURE_FORBID_UNSAFE_VOLUMES", raising=False)
        assert allow_unsafe_volumes() is False

    def test_true(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        monkeypatch.delenv("MERCURE_FORBID_UNSAFE_VOLUMES", raising=False)
        assert allow_unsafe_volumes() is True

    def test_false(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "false")
        assert allow_unsafe_volumes() is False

    def test_forbid_overrides_allow(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_VOLUMES", "true")
        assert allow_unsafe_volumes() is False
        assert forbid_unsafe_volumes() is True

    def test_forbid_truthy(self, monkeypatch):
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_VOLUMES", "yes")
        assert forbid_unsafe_volumes() is True

    def test_forbid_false(self, monkeypatch):
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_VOLUMES", "false")
        assert forbid_unsafe_volumes() is False

    def test_validate_blocked_when_both_set(self, monkeypatch):
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_VOLUMES", "true")
        monkeypatch.setenv("MERCURE_FORBID_UNSAFE_VOLUMES", "true")
        with pytest.raises(ValueError):
            validate_volumes_change("", json.dumps({"/etc/shadow": {"bind": "/x"}}))


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

    def test_save_module_blocks_disallowed_volume(self, test_client, mercure_config):
        mercure_config()
        response = test_client.post(
            "/modules/edit/test_module",
            data={
                "docker_tag": "alpine:3.11",
                "docker_arguments": "",
                "additional_volumes": json.dumps({"/etc/shadow": {"bind": "/x"}}),
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
        assert "/etc/shadow" in response.text

    def test_save_module_allows_safe_volume(self, test_client, mercure_config):
        mercure_config()
        response = test_client.post(
            "/modules/edit/test_module",
            data={
                "docker_tag": "alpine:3.11",
                "docker_arguments": "",
                "additional_volumes": json.dumps(
                    {f"{DEFAULT_VOLUME_BASE}/data": {"bind": "/data", "mode": "ro"}}
                ),
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
        monkeypatch.setenv("MERCURE_ALLOW_UNSAFE_DOCKER_ARGS", "true")
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

    def test_config_editor_blocks_disallowed_volume(self, test_client, mercure_config):
        import common.config as config
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["additional_volumes"] = json.dumps(
            {"/etc/shadow": {"bind": "/x"}}
        )

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "Blocked" in response.text
        assert "/etc/shadow" in response.text

    def test_config_editor_allows_safe_volume(self, test_client, mercure_config):
        import common.config as config
        mercure_config()
        config.read_config()

        new_config = config.mercure.dict()
        new_config["modules"]["test_module"]["additional_volumes"] = json.dumps(
            {f"{DEFAULT_VOLUME_BASE}/data": {"bind": "/data"}}
        )

        response = test_client.post(
            "/configuration/edit",
            data={"editor": json.dumps(new_config)},
            follow_redirects=False,
        )
        assert response.status_code == 303
