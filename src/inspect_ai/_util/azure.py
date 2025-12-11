import os
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

AZURE_SCHEMES = {"az", "abfs", "abfss"}


def apply_azure_fs_options(options: dict[str, Any]) -> None:
    """Inject Azure credentials for fsspec filesystem options on demand."""
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME") or os.getenv(
        "AZURE_ACCOUNT_NAME"
    )
    if account_name:
        options.setdefault("account_name", account_name)

    # Auth resolution order (secure-first):
    # 1. Managed identity / DefaultAzureCredential (implicit if no explicit secret vars set)
    # 2. SAS token (scoped, time-bound)
    # 3. Account key (broad access)
    # 4. Connection string (legacy / broad)
    sas_token = os.getenv("AZURE_STORAGE_SAS_TOKEN") or os.getenv("AZURE_SAS_TOKEN")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY") or os.getenv(
        "AZURE_ACCOUNT_KEY"
    )
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if sas_token:
        options.setdefault("credential", sas_token.lstrip("?"))
    elif account_key:
        options.setdefault("credential", account_key)
    elif connection_string:
        options.setdefault("connection_string", connection_string)

    # Disable caching explicitly (mirrors S3 behavior).
    options.setdefault("use_listings_cache", False)
    options.setdefault("skip_instance_cache", False)


def is_azure_auth_error(error: Exception) -> bool:
    msg = str(error).lower()
    return (
        "noauthenticationinformation" in msg
        or "authenticationfailed" in msg
        or "server failed to authenticate the request" in msg
    )


def is_azure_delete_permission_error(error: Exception) -> bool:
    msg = str(error).lower()
    return (
        "authorizationpermissionmismatch" in msg
        or "not authorized" in msg
        or "this request is not authorized" in msg
        or is_azure_auth_error(error)
    )


T = TypeVar("T")


def call_with_azure_auth_fallback(
    func: Callable[[], T],
    fallback_return_value: T,
) -> T:
    """Call func and swallow Azure auth errors, returning fallback instead."""
    try:
        return func()
    except Exception as ex:
        if is_azure_auth_error(ex):
            return fallback_return_value
        raise


def is_azure_path(path: str) -> bool:
    """Return True if the URI/path uses an Azure-backed scheme."""
    scheme = urlparse(path).scheme.lower()
    return scheme in AZURE_SCHEMES
