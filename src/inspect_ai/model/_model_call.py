import json
from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any, Callable, Final, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, JsonValue, PrivateAttr

from inspect_ai._util.json import jsonable_python
from inspect_ai._util.lineage import (
    Lineage,
    PrefixLineages,
    eq_prefix_len,
    needs_strict_eq,
    strict_eq,
)


def as_error_response(body: object | None) -> dict[str, JsonValue]:
    """Convert an exception body to a safe response dict for ModelCall."""
    if isinstance(body, BaseModel):
        try:
            return cast(dict[str, JsonValue], body.model_dump(warnings=False))
        except Exception:
            return cast(
                dict[str, JsonValue],
                json.loads(body.model_dump_json(warnings=False)),
            )
    if isinstance(body, dict):
        return cast(dict[str, JsonValue], jsonable_python(body))
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
            return {"body": parsed}
        except json.JSONDecodeError:
            return {"body": body}
    return {"body": jsonable_python(body)}


ModelCallFilter = Callable[[JsonValue | None, JsonValue], JsonValue]
"""Filter for transforming or removing some values (e.g. images).

The first parmaeter is the key if the value is a dictionary item.
The second parameter is the value. Return a modified value if appropriate.

"""


CallMessageKey: TypeAlias = Literal["messages", "contents", "input", "inputs"]
"""Key under which a provider wire request carries its messages array."""

CALL_MESSAGE_KEYS: Final[tuple[CallMessageKey, ...]] = (
    "messages",
    "contents",
    "input",
    "inputs",
)


class ModelRequestId(BaseModel):
    """Provider request id from an HTTP response."""

    id: str
    """Request id."""

    header: str
    """Response header the id was read from (e.g. `x-request-id`)."""

    status: int
    """HTTP status code of the response."""


class ModelCall(BaseModel):
    """Model call (raw request/response data)."""

    request: dict[str, JsonValue]
    """Raw data posted to model."""

    response: dict[str, JsonValue] | None = Field(default=None)
    """Raw response data from model (None if call is still pending)."""

    error: bool | None = Field(default=None)
    """Did this model call result in an error."""

    time: float | None = Field(default=None)
    """Time taken for underlying model call."""

    call_refs: list[tuple[int, int]] | None = Field(default=None)
    """Call pool references. Each element is a (start, end_exclusive) range."""

    call_key: str | None = Field(default=None)
    """Key under which messages lived in call.request ('messages' or 'contents')."""

    _filter: ModelCallFilter | None = PrivateAttr(default=None)

    @staticmethod
    def create(
        request: Any,
        response: Any | None,
        filter: ModelCallFilter | None = None,
        time: float | None = None,
    ) -> "ModelCall":
        """Create a ModelCall object.

        Create a ModelCall from arbitrary request and response objects (they might
        be dataclasses, Pydandic objects, dicts, etc.). Converts all values to
        JSON serialiable (exluding those that can't be)

        Args:
           request (Any): Request object (dict, dataclass, BaseModel, etc.)
           response (Any | None): Response object (dict, dataclass, BaseModel, etc.),
               or None if the call is still pending.
           filter (ModelCallFilter): Function for filtering model call data.
           time: Time taken for underlying ModelCall
        """
        request_dict: Any = jsonable_python(request)
        interner = _call_interner.get()
        interned = (
            interner.intern_request(request_dict, filter)
            if interner is not None and isinstance(request_dict, dict)
            else None
        )
        if interned is not None:
            request_dict = interned
        elif filter:
            request_dict = _walk_json_value(None, request_dict, filter)

        response_dict: Any = None
        if response is not None:
            response_dict = jsonable_python(response)
            if filter:
                response_dict = _walk_json_value(None, response_dict, filter)

        if isinstance(request_dict, dict) and (
            response_dict is None or isinstance(response_dict, dict)
        ):
            # jsonable_python output is already JSON-native, and validating
            # would copy every container (losing the interned objects)
            call = ModelCall.model_construct(
                request=request_dict, response=response_dict, time=time
            )
        else:
            call = ModelCall(request=request_dict, response=response_dict, time=time)
        call._filter = filter
        return call

    def set_response(self, response: Any, time: float | None = None) -> None:
        response_dict = jsonable_python(response)
        if self._filter:
            response_dict = cast(
                dict[str, JsonValue],
                _walk_json_value(None, response_dict, self._filter),
            )
        self.response = response_dict
        self.time = time

    def set_error(self, response: Any, time: float | None = None) -> None:
        self.error = True
        self.set_response(response, time)


def _walk_json_value(
    key: JsonValue | None, value: JsonValue, filter: ModelCallFilter
) -> JsonValue:
    value = filter(key, value)
    if isinstance(value, list):
        return [_walk_json_value(None, v, filter) for v in value]
    elif isinstance(value, dict):
        return {k: _walk_json_value(k, v, filter) for k, v in value.items()}
    else:
        return value


_INTERN_SLOTS: Final = 8
"""Request lineages retained per sample (about four interleaved streams)."""

_INTERN_MAX_IDLE: Final = 4 * _INTERN_SLOTS
"""Requests a lineage may go unmatched before it is dropped."""

_HEAVY_STR_LEN: Final = 256 * 1024
"""Strings longer than this (base64 media) are never retained pre-filter."""


class _Heavy:
    """Snapshot stand-in for a message holding a string over ``_HEAVY_STR_LEN``.

    Equal to nothing, so it ends a list comparison; the message is then
    compared by its filtered form, which holds no payload.
    """


_HEAVY = _Heavy()


def _has_heavy_str(value: JsonValue) -> bool:
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            if len(v) > _HEAVY_STR_LEN:
                return True
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
    return False


class CallMessageInterner:
    """Shares wire-message objects across the model calls of a sample.

    Providers rebuild every request from scratch, so each call's message
    list is new objects even where it repeats the previous call. The
    interner matches a new list against recent ones (see
    ``PrefixLineages``) and substitutes the logged objects of the shared
    leading run, so every consumer of logged calls (the transcript, the
    sample buffer, log condensing) sees the same object for the same
    message and compares by identity. The call filter runs only on the
    messages after that run.

    Logged requests are shared across calls, so they must not be mutated
    in place.
    """

    def __init__(self) -> None:
        self._lineages: PrefixLineages[JsonValue] = PrefixLineages(
            _INTERN_SLOTS, _INTERN_MAX_IDLE, _interned_prefix_len
        )

    def intern_request(
        self, request: dict[str, JsonValue], filter: ModelCallFilter | None
    ) -> dict[str, JsonValue] | None:
        """``request`` (filtered) with its message list interned.

        Args:
            request: Jsonable request, before filtering.
            filter: The call's filter, if any.

        Returns:
            The filtered request with interned messages, or ``None`` when it
            has no message list or the filter would replace the request or
            the list itself (the caller then filters it whole).
        """
        msg_key = next((k for k in CALL_MESSAGE_KEYS if k in request), None)
        msgs = request.get(msg_key) if msg_key is not None else None
        if msg_key is None or not isinstance(msgs, list):
            return None
        if filter is not None and (
            filter(None, request) is not request or filter(msg_key, msgs) is not msgs
        ):
            return None
        logged = self.intern(msgs, msg_key, filter)
        return {
            k: logged
            if k == msg_key
            else (_walk_json_value(k, v, filter) if filter else v)
            for k, v in request.items()
        }

    def intern(
        self,
        msgs: list[JsonValue],
        msg_key: CallMessageKey,
        filter: ModelCallFilter | None,
    ) -> list[JsonValue]:
        """Logged (filtered) messages for ``msgs``, reusing earlier objects.

        Args:
            msgs: Jsonable wire messages, before filtering.
            msg_key: Request key the messages live under.
            filter: The call's filter, if any.

        Returns:
            The filtered messages, sharing objects with earlier calls for
            the leading run they repeat.
        """
        key = (msg_key, filter)
        match = self._lineages.match(key, msgs)
        n = match.length
        lineage = match.lineage
        logged = match.entries
        snapshots = lineage.snapshots[:n] if lineage else []
        strict = lineage.strict[:n] if lineage else []
        for msg in msgs[n:]:
            out = _walk_json_value(None, msg, filter) if filter else msg
            logged.append(out)
            if filter is not None and _has_heavy_str(msg):
                snapshots.append(_HEAVY)
                strict.append(False)
            else:
                snapshots.append(msg)
                strict.append(needs_strict_eq(msg))
        self._lineages.record(key, match, snapshots, strict, logged)
        return list(logged)


def _interned_prefix_len(msgs: Sequence[object], lineage: Lineage[JsonValue]) -> int:
    """Shared leading run, comparing ``_HEAVY`` snapshots by filtered form."""
    filter = cast(tuple[CallMessageKey, ModelCallFilter | None], lineage.key)[1]
    snapshots = lineage.snapshots
    limit = min(len(msgs), len(snapshots))
    n = 0
    while True:
        n += eq_prefix_len(msgs[n:], snapshots[n:], lineage.strict[n:])
        if n >= limit or snapshots[n] is not _HEAVY or filter is None:
            return n
        walked = _walk_json_value(None, cast(JsonValue, msgs[n]), filter)
        if not strict_eq(walked, lineage.entries[n]):
            return n
        n += 1


_call_interner: ContextVar[CallMessageInterner | None] = ContextVar(
    "call_interner", default=None
)


def init_call_interner(enabled: bool = True) -> None:
    """Start a fresh message interner for the current context (one per sample).

    Args:
        enabled: Whether to intern; transcripts that drop most calls'
            payloads pass ``False``, so calls skip the comparison.
    """
    _call_interner.set(CallMessageInterner() if enabled else None)
