"""The `sentinel` field a sidecar adds to an agent call's reply or refusal, as each provider's SDK hands it over."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SentinelStep(BaseModel):
    """One step the sidecar judged during the call."""

    model_config = ConfigDict(extra="allow")

    stage: Literal["model_input", "model_output", "tool_call", "tool_result"]
    call: str | None = None
    original: dict[str, Any] | None = None
    decision: dict[str, Any]
    recorded: list[dict[str, Any]] | None = None


class WithheldTurn(BaseModel):
    """The model's turn, as the sidecar was handed it, with what the model is told of each call taken out."""

    model_config = ConfigDict(extra="allow")

    message: dict[str, Any]
    results: dict[str, str]


class SentinelField(BaseModel):
    """What a sidecar decided during one agent call."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    outcome: Literal["proceed", "reject", "terminate"]
    trimmed: bool | None = None
    steps: list[SentinelStep] = Field(default_factory=list)
    withheld: WithheldTurn | None = None
    proposed: WithheldTurn | None = None


class ReceivedField:
    """The field of the latest attempt at a call, once a provider has handed it over."""

    def __init__(self) -> None:
        self.field: dict[str, Any] | None = None


_received: ContextVar[ReceivedField | None] = ContextVar(
    "sentinel_field_received", default=None
)


@contextmanager
def receiving_field() -> Iterator[ReceivedField]:
    """Collect the `sentinel` field of an agent call through a sidecar, for the providers to report it into."""
    received = ReceivedField()
    token = _received.set(received)
    try:
        yield received
    finally:
        _received.reset(token)


def report_sentinel_field(source: object) -> None:
    """Report the field from a provider SDK object that may carry it: a reply, or a stream's last event.

    The SDKs keep a field they don't know in the object's `model_extra`, and drop it when they put a stream together, so a stream's events are reported as they are read.
    """
    received = _received.get()
    if received is None:
        return
    extra = getattr(source, "model_extra", None)
    if isinstance(extra, dict) and isinstance(extra.get("sentinel"), dict):
        received.field = extra["sentinel"]


def report_sentinel_error(ex: BaseException) -> None:
    """Report the field from a provider SDK's error: beside the error, as Envoy puts it, or at `error.provider_specific_fields.sentinel`, as LiteLLM does."""
    received = _received.get()
    if received is None:
        return
    for body in _error_bodies(ex):
        found = body.get("sentinel")
        error = body.get("error")
        nested = body.get("provider_specific_fields")
        if not isinstance(found, dict) and isinstance(error, dict):
            nested = error.get("provider_specific_fields")
        if not isinstance(found, dict) and isinstance(nested, dict):
            found = nested.get("sentinel")
        if isinstance(found, dict):
            received.field = found
            return


def _error_bodies(ex: BaseException) -> Iterator[dict[str, Any]]:
    # Anthropic's SDK keeps the whole body; OpenAI's keeps only `error`, so
    # the top level is read from the response, which it has already read
    body = getattr(ex, "body", None)
    if isinstance(body, dict):
        yield body
    response = getattr(ex, "response", None)
    try:
        whole = response.json() if response is not None else None
    except Exception:
        whole = None
    if isinstance(whole, dict):
        yield whole
