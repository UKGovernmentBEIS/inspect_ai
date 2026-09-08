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

from typing_extensions import TypedDict

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


class ResponseFilterError(Exception):
    """A `response_filter` raised while transforming a model's output.

    A response filter is eval logic, not a passive observer of the model
    response, so a failure in it should propagate and fail the sample
    (attributed to the filter) rather than being reported to the scaffold as
    a model/provider error. Wrapping the original exception gives both the
    sandbox path (`_forward_provider_errors` excludes this type the way it
    excludes `LimitExceededError`) and the in-process path one exception
    type to raise, instead of each path handling filter failures
    differently. The original exception is preserved as `__cause__`.
    """


class ProviderErrorPayload(TypedDict):
    """Forwardable provider-error detail carried under `PROVIDER_ERROR_KEY`."""

    status: int | None
    message: str


def provider_error_payload(ex: Exception) -> ProviderErrorPayload:
    """Extract a forwardable provider-error payload from an exception.

    Best-effort: recovers the HTTP status (from `ModelGenerateError` or a raw
    provider SDK exception) and a clean message, degrading to `str(ex)` when no
    structured detail is available.
    """
    message = getattr(ex, "provider_message", None) or str(ex)
    return ProviderErrorPayload(status=status_code_of(ex), message=message)
