"""
sigstore.py
===========
Wraps the cosign CLI to verify OCI image signatures before a container runs.
Raises SigstoreVerificationError on failure.
"""

import shutil
import subprocess
from typing import Optional

import common.config as config

logger = config.get_logger()


class SigstoreVerificationError(Exception):
    """Raised when cosign signature verification fails."""


def verify_image(
    docker_tag: str,
    sigstore_verify: Optional[str] = "False",
    sigstore_cert_identity: Optional[str] = "",
    sigstore_cert_oidc_issuer: Optional[str] = "",
    sigstore_public_key: Optional[str] = "",
) -> None:
    """Verify an OCI image signature with cosign.

    Two modes are supported:
      - Keyless (OIDC): requires sigstore_cert_identity and sigstore_cert_oidc_issuer.
      - Key-based:      requires sigstore_public_key.

    Keyless takes precedence when both are supplied.

    Args:
        docker_tag: The fully-qualified image reference to verify.
        sigstore_verify: "True" to enable verification, anything else to skip.
        sigstore_cert_identity: Certificate identity for keyless (OIDC) verification.
        sigstore_cert_oidc_issuer: OIDC issuer URL for keyless verification.
        sigstore_public_key: Path to the .pub file for key-based verification.

    Raises:
        SigstoreVerificationError: When verification is enabled but fails or is
            misconfigured.
    """
    if (sigstore_verify or "").strip() != "True":
        return

    if not docker_tag:
        raise SigstoreVerificationError("No docker tag supplied for Sigstore verification.")

    cosign = shutil.which("cosign")
    if not cosign:
        raise SigstoreVerificationError(
            "cosign binary not found. Install cosign to use Sigstore verification."
        )

    cert_identity = (sigstore_cert_identity or "").strip()
    cert_oidc_issuer = (sigstore_cert_oidc_issuer or "").strip()
    public_key = (sigstore_public_key or "").strip()

    # Determine verification mode: keyless takes precedence over key-based.
    if cert_identity and cert_oidc_issuer:
        cmd = [
            cosign, "verify",
            "--certificate-identity", cert_identity,
            "--certificate-oidc-issuer", cert_oidc_issuer,
            docker_tag,
        ]
        mode = "keyless"
    elif public_key:
        cmd = [
            cosign, "verify",
            "--key", public_key,
            docker_tag,
        ]
        mode = "key-based"
    else:
        raise SigstoreVerificationError(
            "Sigstore verification is enabled but no verification parameters are set. "
            "Provide either (certificate identity + OIDC issuer) for keyless verification "
            "or a public key path for key-based verification."
        )

    logger.info(f"Running Sigstore ({mode}) verification for image: {docker_tag}")
    logger.debug(f"cosign command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise SigstoreVerificationError(
            f"cosign verification timed out for image: {docker_tag}"
        )
    except Exception as e:
        raise SigstoreVerificationError(
            f"Failed to run cosign for image {docker_tag}: {e}"
        ) from e

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error(f"Sigstore verification failed for {docker_tag}: {stderr}")
        raise SigstoreVerificationError(
            f"Sigstore verification failed for image '{docker_tag}': {stderr}"
        )

    logger.info(f"Sigstore verification passed for image: {docker_tag}")
