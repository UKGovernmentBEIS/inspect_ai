"""Shared helpers for forwarding provider errors through the agent bridge.

The sandbox model proxy (a separate, shipped binary that cannot import
`inspect_ai`) forwards provider errors to the proxied agent instead of crashing.
The host side serializes the error into the RPC `result` channel under
`PROVIDER_ERROR_KEY`; the proxy detects that key and emits a provider-dialect
error response.

`PROVIDER_ERROR_KEY` is mirrored as a literal in the proxy
(`inspect_sandbox_tools/_agent_bridge/proxy.py`) since the proxy cannot import
this module — keep the two in sync.
"""

from pydantic import JsonValue
from typing_extensions import NotRequired, TypedDict

from inspect_ai._util.http import status_code_of

PROVIDER_ERROR_KEY = "__inspect_provider_error__"
"""Reserved result key marking an RPC result as a forwardable provider error.

Mirrored as a literal in the sandbox proxy; keep both in sync.
"""


class BridgePolicyError(Exception):
    """A bridged request asked for something the bridge is configured to withhold.

    Carries `status_code` so `provider_error_payload()` reports a 400 rather than
    an unrecoverable status — a policy denial is a deterministic client error, not
    a bug in our request translation, and should not be logged with a traceback.
    """

    status_code = 400


class ProviderErrorPayload(TypedDict):
    """Forwardable provider-error detail carried under `PROVIDER_ERROR_KEY`."""

    status: int | None
    message: str
    body: NotRequired[JsonValue]


def provider_error_payload(ex: Exception) -> ProviderErrorPayload:
    """Extract a forwardable provider-error payload from an exception.

    The retry layer raises ``RetryError`` after retries exhaust. Prefer its
    explicit cause, then its final failed attempt, so callers receive the
    originating provider error rather than a tenacity representation.
    """
    from tenacity import RetryError

    if isinstance(ex, RetryError):
        if isinstance(ex.__cause__, Exception):
            ex = ex.__cause__
        else:
            last_attempt = getattr(ex, "last_attempt", None)
            if last_attempt is not None and last_attempt.done():
                attempt_error = last_attempt.exception()
                if isinstance(attempt_error, Exception):
                    ex = attempt_error

    try:
        message = getattr(ex, "provider_message", None) or str(ex)
    except Exception:
        message = type(ex).__name__
    payload = ProviderErrorPayload(status=status_code_of(ex), message=message)

    try:
        from openai import APIStatusError
    except ImportError:
        return payload

    provider_error: Exception | None = ex
    while provider_error is not None:
        if isinstance(provider_error, APIStatusError) and isinstance(
            provider_error.body, dict
        ):
            body = provider_error.body
            body_message = body.get("message")
            if isinstance(body_message, str):
                payload["message"] = body_message
            payload["body"] = body
            return payload
        provider_error = (
            provider_error.__cause__
            if isinstance(provider_error.__cause__, Exception)
            else None
        )

    return payload
