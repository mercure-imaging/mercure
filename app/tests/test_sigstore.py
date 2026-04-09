"""
test_sigstore.py
================
Unit tests for process/sigstore.py — covers all paths:
disabled, missing params, keyless success/failure, key-based, timeout, precedence.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from process.sigstore import SigstoreVerificationError, verify_image


# ---------------------------------------------------------------------------
# 1. Disabled — should be a no-op regardless of other params
# ---------------------------------------------------------------------------

def test_disabled_by_default():
    """verify_image does nothing when sigstore_verify is the default 'False'."""
    verify_image("myrepo/myimage:latest")  # must not raise


def test_disabled_explicit_false():
    verify_image("myrepo/myimage:latest", sigstore_verify="False")


def test_disabled_empty_string():
    verify_image("myrepo/myimage:latest", sigstore_verify="")


def test_disabled_none():
    verify_image("myrepo/myimage:latest", sigstore_verify=None)


# ---------------------------------------------------------------------------
# 2. Enabled — missing cosign binary
# ---------------------------------------------------------------------------

def test_cosign_not_installed():
    with patch("process.sigstore.shutil.which", return_value=None):
        with pytest.raises(SigstoreVerificationError, match="cosign binary not found"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
                sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            )


# ---------------------------------------------------------------------------
# 3. Enabled — no verification parameters supplied
# ---------------------------------------------------------------------------

def test_enabled_no_params():
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"):
        with pytest.raises(SigstoreVerificationError, match="no verification parameters"):
            verify_image("myrepo/myimage:latest", sigstore_verify="True")


def test_enabled_only_cert_identity_missing_issuer():
    """Only identity without issuer → not enough for keyless; no key either."""
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"):
        with pytest.raises(SigstoreVerificationError, match="no verification parameters"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
            )


def test_enabled_only_issuer_missing_identity():
    """Only issuer without identity → not enough for keyless; no key either."""
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"):
        with pytest.raises(SigstoreVerificationError, match="no verification parameters"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            )


# ---------------------------------------------------------------------------
# 4. Keyless verification — success
# ---------------------------------------------------------------------------

def test_keyless_success():
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stderr = ""

    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", return_value=completed) as mock_run:
        verify_image(
            "myrepo/myimage:latest",
            sigstore_verify="True",
            sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
            sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
        )

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "--certificate-identity" in cmd
    assert "--certificate-oidc-issuer" in cmd
    assert "--key" not in cmd


# ---------------------------------------------------------------------------
# 5. Keyless verification — failure (non-zero exit)
# ---------------------------------------------------------------------------

def test_keyless_failure():
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 1
    completed.stderr = "error: no matching signatures"

    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", return_value=completed):
        with pytest.raises(SigstoreVerificationError, match="no matching signatures"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
                sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            )


# ---------------------------------------------------------------------------
# 6. Key-based verification — success
# ---------------------------------------------------------------------------

def test_key_based_success():
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stderr = ""

    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", return_value=completed) as mock_run:
        verify_image(
            "myrepo/myimage:latest",
            sigstore_verify="True",
            sigstore_public_key="/etc/mercure/cosign.pub",
        )

    cmd = mock_run.call_args[0][0]
    assert "--key" in cmd
    assert "/etc/mercure/cosign.pub" in cmd
    assert "--certificate-identity" not in cmd


# ---------------------------------------------------------------------------
# 7. Key-based verification — failure
# ---------------------------------------------------------------------------

def test_key_based_failure():
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 1
    completed.stderr = "error: invalid signature"

    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", return_value=completed):
        with pytest.raises(SigstoreVerificationError, match="invalid signature"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_public_key="/etc/mercure/cosign.pub",
            )


# ---------------------------------------------------------------------------
# 8. Timeout
# ---------------------------------------------------------------------------

def test_timeout():
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="cosign", timeout=60)):
        with pytest.raises(SigstoreVerificationError, match="timed out"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
                sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            )


# ---------------------------------------------------------------------------
# 9. Unexpected subprocess exception
# ---------------------------------------------------------------------------

def test_subprocess_exception():
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", side_effect=OSError("Permission denied")):
        with pytest.raises(SigstoreVerificationError, match="Failed to run cosign"):
            verify_image(
                "myrepo/myimage:latest",
                sigstore_verify="True",
                sigstore_public_key="/etc/mercure/cosign.pub",
            )


# ---------------------------------------------------------------------------
# 10. Keyless takes precedence over key-based when both supplied
# ---------------------------------------------------------------------------

def test_keyless_precedence_over_key_based():
    """When both keyless params and a public key are provided, keyless wins."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stderr = ""

    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"), \
         patch("process.sigstore.subprocess.run", return_value=completed) as mock_run:
        verify_image(
            "myrepo/myimage:latest",
            sigstore_verify="True",
            sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
            sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            sigstore_public_key="/etc/mercure/cosign.pub",
        )

    cmd = mock_run.call_args[0][0]
    assert "--certificate-identity" in cmd
    assert "--certificate-oidc-issuer" in cmd
    assert "--key" not in cmd


# ---------------------------------------------------------------------------
# 11. No docker tag with verification enabled
# ---------------------------------------------------------------------------

def test_no_docker_tag():
    with patch("process.sigstore.shutil.which", return_value="/usr/bin/cosign"):
        with pytest.raises(SigstoreVerificationError, match="No docker tag"):
            verify_image(
                "",
                sigstore_verify="True",
                sigstore_cert_identity="https://github.com/org/repo/.github/workflows/build.yml@refs/heads/main",
                sigstore_cert_oidc_issuer="https://token.actions.githubusercontent.com",
            )
