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

import threading
from typing import Any

import anyio
from anyio import to_thread

from inspect_ai._util.error import PrerequisiteError

DEFAULT_OAUTH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# google-genai's dev-endpoint client constructor rejects an empty api_key; this
# placeholder satisfies it and is overridden by the injected Authorization header.
OAUTH_PLACEHOLDER_API_KEY = "oauth-placeholder"

# Bound on the token-endpoint round-trip (google-auth's transport default is
# 120s). Keeps an abandoned refresh thread from holding the refresh lock — and
# so blocking the next refresh attempt — for long after its waiter was cancelled.
REFRESH_TIMEOUT_SECONDS = 30


class GoogleOAuthCredentials:
    """Cancellation-safe refresh wrapper around google-auth credentials.

    The refresh is a blocking token-endpoint round-trip, so ``ensure_valid``
    offloads it to a worker thread (keeping the event loop responsive) with
    ``abandon_on_cancel=True`` so the awaiting task can be cancelled
    immediately (e.g. by attempt timeouts) rather than being shielded until
    the thread finishes.
    """

    def __init__(self, credentials: Any) -> None:
        """Wrap a google-auth credentials object.

        Args:
            credentials: A google-auth credentials object.
        """
        self.credentials = credentials
        # Single-flight for the common path: one task offloads the refresh
        # while the rest wait (cancellably) here and re-check validity.
        self._task_lock = anyio.Lock()
        # Cross-thread backstop: a cancelled waiter abandons its worker thread
        # mid-refresh (releasing _task_lock), so a subsequent attempt can start
        # a new refresh thread while the abandoned one still runs. google-auth
        # credentials are not thread-safe for concurrent refresh, so the actual
        # refresh is additionally serialized across threads.
        self._thread_lock = threading.Lock()

    async def ensure_valid(self) -> None:
        """Refresh the credentials in a worker thread if they are not valid."""
        if self.credentials.valid:
            return
        async with self._task_lock:
            if not self.credentials.valid:
                await to_thread.run_sync(self._refresh, abandon_on_cancel=True)

    def _refresh(self) -> None:
        with self._thread_lock:
            if self.credentials.valid:
                return
            from google.auth.transport.requests import Request

            request = Request()

            def bounded_request(*args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("timeout", REFRESH_TIMEOUT_SECONDS)
                return request(*args, **kwargs)

            self.credentials.refresh(bounded_request)

    def invalidate(self) -> None:
        """Force the next ``ensure_valid`` to mint a fresh token (no I/O)."""
        self.credentials.token = None

    def headers(self, quota_project_id: str | None) -> dict[str, str]:
        """Build request headers carrying the OAuth bearer token.

        Performs no I/O — callers must first ensure the token is fresh via
        ``ensure_valid``.

        Args:
            quota_project_id: Project to bill/quota against
                (``x-goog-user-project``), or ``None`` to omit the header.

        Returns:
            Headers to merge into the request (``Authorization`` and, if
            provided, ``x-goog-user-project``).
        """
        headers = {"Authorization": f"Bearer {self.credentials.token}"}
        if quota_project_id:
            headers["x-goog-user-project"] = quota_project_id
        return headers


def resolve_google_credentials(scopes: list[str] | None) -> GoogleOAuthCredentials:
    """Load Application Default Credentials for the Gemini Developer API.

    Args:
        scopes: OAuth scopes to request (defaults to cloud-platform).

    Returns:
        Refreshable wrapper around the ADC credentials.
    """
    try:
        import google.auth
    except ImportError:
        raise PrerequisiteError(
            "OAuth/ADC support for the Google provider requires the `google-auth` "
            "package (installed automatically with `google-genai`)."
        )
    creds, _ = google.auth.default(scopes=scopes or DEFAULT_OAUTH_SCOPES)
    return GoogleOAuthCredentials(creds)
