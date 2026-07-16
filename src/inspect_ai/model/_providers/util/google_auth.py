"""OAuth / ADC credential support for the Gemini Developer API.

The Gemini Developer API endpoint (``generativelanguage.googleapis.com``) is
authenticated by ``google-genai`` with an API key only — the SDK's
``credentials=`` argument is consulted for Vertex AI exclusively. Some
deployments (e.g. partner-served models) are reachable only via an OAuth bearer
token (Application Default Credentials) plus an ``x-goog-user-project`` quota
header, with no API key available.

These helpers resolve google-auth credentials and build the request headers that
carry the bearer token. The provider passes a placeholder API key to satisfy the
``google-genai`` client constructor and injects the ``Authorization`` header
(which overrides the placeholder ``x-goog-api-key`` on the server side).
"""

from typing import Any

from inspect_ai._util.error import PrerequisiteError

DEFAULT_OAUTH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# google-genai's dev-endpoint client constructor rejects an empty api_key; this
# placeholder satisfies it and is overridden by the injected Authorization header.
OAUTH_PLACEHOLDER_API_KEY = "oauth-placeholder"


def resolve_google_credentials(
    credentials: Any | None, scopes: list[str] | None
) -> Any:
    """Resolve google-auth credentials for the Gemini Developer API.

    Args:
        credentials: An explicit ``google.auth.credentials.Credentials`` object,
            or ``None`` to load Application Default Credentials.
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
    if credentials is not None:
        return credentials
    creds, _ = google.auth.default(scopes=scopes or DEFAULT_OAUTH_SCOPES)
    return creds


def google_oauth_headers(
    credentials: Any, quota_project_id: str | None
) -> dict[str, str]:
    """Build request headers carrying a fresh OAuth bearer token.

    Refreshes the credentials if they are not currently valid, so callers that
    invoke this per-request get automatic token refresh.

    Args:
        credentials: A google-auth credentials object.
        quota_project_id: Project to bill/quota against (``x-goog-user-project``),
            or ``None`` to omit the header.

    Returns:
        Headers to merge into the request (``Authorization`` and, if provided,
        ``x-goog-user-project``).
    """
    from google.auth.transport.requests import Request

    if not credentials.valid:
        credentials.refresh(Request())
    headers = {"Authorization": f"Bearer {credentials.token}"}
    if quota_project_id:
        headers["x-goog-user-project"] = quota_project_id
    return headers
