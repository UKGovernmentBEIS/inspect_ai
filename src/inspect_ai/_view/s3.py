"""S3-specific helpers used across Inspect view components."""

_S3_AUTH_KEYWORDS = (
    # botocore ClientError strings embed the camel-case code, e.g.
    # "An error occurred (AccessDenied) when calling ..."
    "accessdenied",
    # s3fs raises bare PermissionError("Access Denied") for the same condition
    "access denied",
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
    "expiredtoken",
    "auth failure",
    "unable to locate credentials",
    "no credentials were found",
    "the security token included in the request is invalid",
)


def is_s3_path(path: str) -> bool:
    """Return True if the path targets an S3 filesystem."""
    return path.lower().startswith(("s3://", "s3a://"))


def should_suppress_s3_error(path: str, error: Exception) -> bool:
    """Return True if an S3 auth/credential issue should be downgraded to a warning.

    Mirrors :func:`should_suppress_azure_error`: any denial-class failure
    (wrong credentials *or* insufficient IAM permissions on the bucket) is
    degraded to a diagnostic warning with an empty/partial listing rather
    than aborting the whole log view with a raw provider error.
    """
    if not is_s3_path(path):
        return False
    lowered = str(error).lower()
    return any(keyword in lowered for keyword in _S3_AUTH_KEYWORDS)


def s3_warning_hint(path: str, error: Exception) -> str:
    """Diagnostic guidance for S3 listing/authentication issues."""
    return (
        "S3 authentication failed while probing "
        f"'{path}'. Suppressed stack trace. Guidance: (a) verify credentials with "
        "'aws sts get-caller-identity' or set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY "
        "(plus AWS_SESSION_TOKEN for temporary credentials); (b) confirm the identity "
        "has s3:ListBucket and s3:GetObject permission on the bucket; (c) ensure "
        f"AWS_REGION/AWS_DEFAULT_REGION match the bucket. Original error: {error}"
    )
