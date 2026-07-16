"""OAuth / ADC credential support for the Gemini Developer API.

The Gemini Developer API endpoint (``generativelanguage.googleapis.com``) is
authenticated by ``google-genai`` with an API key only — the SDK's
``credentials=`` argument is consulted for Vertex AI exclusively. Some
deployments (e.g. partner-served models) are reachable only via an OAuth bearer
token (Application Default Credentials) plus an ``x-goog-user-project`` quota
header, with no API key available.

These helpers load Application Default Credentials and build the request
headers that carry the bearer token. The provider passes a placeholder API key
to satisfy the ``google-genai`` client constructor and injects the
``Authorization`` header (which overrides the placeholder ``x-goog-api-key`` on
the server side).
"""

from typing import Any

import anyio

from inspect_ai._util.error import PrerequisiteError

DEFAULT_OAUTH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# google-genai's dev-endpoint client constructor rejects an empty api_key; this
# placeholder satisfies it and is overridden by the injected Authorization header.
OAUTH_PLACEHOLDER_API_KEY = "oauth-placeholder"


def resolve_google_credentials(scopes: list[str] | None) -> Any:
    """Load Application Default Credentials for the Gemini Developer API.

    Args:
        scopes: OAuth scopes to request (defaults to cloud-platform).

    Returns:
        A google-auth credentials object.
    """
    try:
        import google.auth
    except ImportError:
        raise PrerequisiteError(
            "OAuth/ADC support for the Google provider requires the `google-auth` "
            "package (installed automatically with `google-genai`)."
        )
    creds, _ = google.auth.default(scopes=scopes or DEFAULT_OAUTH_SCOPES)
    return creds


async def ensure_google_credentials_valid(
    credentials: Any, refresh_lock: anyio.Lock
) -> None:
    """Refresh the credentials in a worker thread if they are not valid.

    The refresh is a blocking token-endpoint round-trip, so it is offloaded to
    a worker thread to keep the event loop responsive and the awaiting task
    cancellable (e.g. by attempt timeouts). Offloading introduces real
    concurrency, so ``refresh_lock`` is required: google-auth credential
    objects are not thread-safe for concurrent refresh, and all in-flight
    samples reach token expiry at once. Waiters re-check validity after
    acquiring the lock so only one refresh runs per expiry.

    Args:
        credentials: A google-auth credentials object.
        refresh_lock: Lock serializing refreshes of this credentials object.
    """
    if credentials.valid:
        return
    async with refresh_lock:
        if not credentials.valid:
            from google.auth.transport.requests import Request

            await anyio.to_thread.run_sync(credentials.refresh, Request())


def google_oauth_headers(
    credentials: Any, quota_project_id: str | None
) -> dict[str, str]:
    """Build request headers carrying the OAuth bearer token.

    Performs no I/O — callers must first ensure the token is fresh via
    ``ensure_google_credentials_valid``.

    Args:
        credentials: A google-auth credentials object.
        quota_project_id: Project to bill/quota against (``x-goog-user-project``),
            or ``None`` to omit the header.

    Returns:
        Headers to merge into the request (``Authorization`` and, if provided,
        ``x-goog-user-project``).
    """
    headers = {"Authorization": f"Bearer {credentials.token}"}
    if quota_project_id:
        headers["x-goog-user-project"] = quota_project_id
    return headers
