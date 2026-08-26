"""Helpers for treating remote-filesystem auth failures as degraded listings."""

from urllib.parse import urlparse

from botocore.exceptions import ClientError, NoCredentialsError

from inspect_ai._util.azure import (
    AZURE_SCHEMES,
    azure_warning_hint,
    should_suppress_azure_error,
)

S3_SCHEME = "s3"
GCS_SCHEMES = {"gs", "gcs"}


def _is_s3_auth_error(error: Exception) -> bool:
    """Return True if ``error`` is an S3 credential/auth failure."""
    if isinstance(error, NoCredentialsError):
        return True
    if isinstance(error, ClientError):
        code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if code in {
            "NoCredentialsError",
            "CredentialRetrievalError",
            "InvalidAccessKeyId",
            "SignatureDoesNotMatch",
            "AccessDenied",
        }:
            return True
    msg = str(error).lower()
    return "credential" in msg or "access key" in msg or "signature" in msg


def _is_gcs_auth_error(error: Exception) -> bool:
    """Return True if ``error`` is a Google Cloud Storage auth failure."""
    msg = str(error).lower()
    return any(
        phrase in msg
        for phrase in (
            "credential",
            "authentication",
            "unauthenticated",
            "invalid credentials",
            "anonymous caller",
            "login required",
        )
    )


def should_suppress_remote_auth_error(path: str, error: Exception) -> bool:
    """Return True if a remote filesystem auth issue should be downgraded.

    Auth failures for Azure, S3, and GCS are treated leniently so that log
    listings degrade to an empty/warning result rather than surfacing a raw
    provider exception to the user.
    """
    scheme = urlparse(path).scheme.lower()
    if scheme in AZURE_SCHEMES:
        return should_suppress_azure_error(path, error)
    if scheme == S3_SCHEME:
        return _is_s3_auth_error(error)
    if scheme in GCS_SCHEMES:
        return _is_gcs_auth_error(error)
    return False


def remote_auth_warning_hint(path: str, error: Exception) -> str:
    """Diagnostic guidance for remote listing/authentication issues."""
    scheme = urlparse(path).scheme.lower()
    if scheme in AZURE_SCHEMES:
        return azure_warning_hint(path, error)
    if scheme == S3_SCHEME:
        return (
            "S3 authentication failed while probing "
            f"'{path}'. Suppressed stack trace. Guidance: ensure AWS credentials are "
            "configured (e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, SSO, or an "
            f"IAM role) and the bucket is accessible. Original error: {error}"
        )
    if scheme in GCS_SCHEMES:
        return (
            "Google Cloud Storage authentication failed while probing "
            f"'{path}'. Suppressed stack trace. Guidance: ensure Application Default "
            "Credentials are configured (e.g. `gcloud auth application-default login`). "
            f"Original error: {error}"
        )
    return f"Authentication failed while probing '{path}': {error}"
