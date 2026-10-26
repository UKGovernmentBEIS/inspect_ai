"""The `sentinel` field a sidecar adds to an agent call's reply or refusal, as each provider's SDK hands it over."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
    """The field of the latest attempt at a call, once a provider has handed it over, and the id the attempt was sent under."""

    def __init__(self, sidecar: Any = None) -> None:
        self.sidecar = sidecar
        """The sidecar the call goes through, which `request_result` asks."""
        self.field: dict[str, Any] | None = None
        self.request_id: str | None = None
        self.looked: Any = None
        """What `request_result` said of a refusal that came without the field."""


_received: ContextVar[ReceivedField | None] = ContextVar(
    "sentinel_field_received", default=None
)


@contextmanager
def receiving_field(sidecar: Any = None) -> Iterator[ReceivedField]:
    """Collect the `sentinel` field of an agent call through a sidecar, for the providers to report it into."""
    received = ReceivedField(sidecar)
    token = _received.set(received)
    try:
        yield received
    finally:
        _received.reset(token)


def begin_attempt() -> None:
    """Forget the field of an earlier attempt at the current agent call, which a retry supersedes."""
    received = _received.get()
    if received is not None:
        received.field = None
        received.request_id = None
        received.looked = None


def current_receiving() -> ReceivedField | None:
    """What is collected of the current agent call through a sidecar, or None for any other call."""
    return _received.get()


def report_request_id(request_id: str) -> None:
    """Report the `x-irid` the current agent call is sent under, by which the sidecar's `request_result` finds it."""
    received = _received.get()
    if received is not None:
        received.request_id = request_id


def received_field() -> SentinelField | None:
    """The field of the current agent call's latest attempt, or None if it had none.

    Raises:
        ValueError: If the field isn't one this Inspect can read.
    """
    received = _received.get()
    if received is None or received.field is None:
        return None
    return parse_field(received.field)


def parse_field(field: dict[str, Any]) -> SentinelField:
    """A `sentinel` field, as a sidecar writes it.

    Raises:
        ValueError: If the field isn't one this Inspect can read.
    """
    try:
        return SentinelField.model_validate(field)
    except ValidationError as ex:
        raise ValueError(f"The sidecar's sentinel field can't be read: {ex}") from ex


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
