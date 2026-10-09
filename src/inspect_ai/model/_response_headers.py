"""Experimental per-attempt HTTP response headers for model calls.

A proxy or gateway in front of a model can tell its client things in response
headers (a sentinel naming its decision, a gateway naming the upstream that
served the request). This module gives the model layer one place to keep the
headers of the latest HTTP response for each attempt of a model call, so they
can be read after the provider returns or raises.

Providers that go through Inspect's HTTP hooks (the shared `httpx` client
factory or `HttpxHooks`) record headers automatically. Providers with their
own HTTP stacks (Azure AI, SageMaker) call `record_response_headers()` from
their response paths.

The recording scope is the current model-call attempt: each attempt opens a
fresh scope, recordings replace earlier ones within the attempt (the last
response in the attempt wins, including side requests a provider makes
through the shared factory inside one attempt), and the scope closes at
attempt exit so unrelated HTTP traffic never leaks into a call. The headers
of the last attempt remain readable via `current_response_headers()` after
the call completes. Per-attempt history travels on `ModelCall.response_headers`
(and on `ModelGenerateError` for provider errors that carry a call).

Own-stack coverage: SageMaker records on both successful and failed invokes
(botocore `ResponseMetadata.HTTPHeaders`); Azure AI records on the error path
(azure-core carries the raw response on the exception) — successful Azure
calls surface parsed results without raw headers. Repeated header names are
flattened as the underlying transport presents them (httpx and boto3 both
comma-join repeats).
"""

from contextvars import ContextVar
from typing import Mapping

_attempt_response_headers: ContextVar[dict[str, str] | None] = ContextVar(
    "inspect_ai_attempt_response_headers", default=None
)
_last_response_headers: ContextVar[dict[str, str] | None] = ContextVar(
    "inspect_ai_last_response_headers", default=None
)


def record_response_headers(headers: Mapping[str, str]) -> None:
    """Record HTTP response headers for the current model-call attempt.

    Experimental: providers with their own HTTP stacks call this from their
    response paths. Recordings outside an active model-call attempt are
    ignored, so unrelated HTTP traffic never leaks into a call. Keys are
    lowercased (HTTP header names are case-insensitive; the shared httpx
    stack lowercases while own-stack SDKs keep wire casing, so normalizing
    here keeps `ModelCall.response_headers` uniform).
    """
    if _attempt_response_headers.get() is not None:
        _attempt_response_headers.set(
            {key.lower(): value for key, value in headers.items()}
        )


def current_response_headers() -> dict[str, str] | None:
    """Headers of the most recent completed model-call attempt.

    Experimental: returns `None` when no attempt has recorded headers.
    Prefer `ModelCall.response_headers` for per-attempt data once the call
    completes; this read is for callers that need the headers of an attempt
    which ended in a raise without producing a call. The recording scope
    closes when the attempt ends, so HTTP traffic unrelated to model calls
    never overwrites this value.
    """
    headers = _last_response_headers.get()
    return dict(headers) if headers else None


def begin_attempt_response_headers() -> None:
    """Open the recording scope for one model-call attempt (internal)."""
    _attempt_response_headers.set({})


def finish_attempt_response_headers() -> None:
    """Close the attempt scope, snapshotting it as the last attempt (internal).

    Called on every attempt exit (return, raise, cancellation): the captured
    headers become readable via `current_response_headers()` and the
    recording scope is closed, so later non-model traffic is ignored.
    """
    _last_response_headers.set(_attempt_response_headers.get() or None)
    _attempt_response_headers.set(None)
