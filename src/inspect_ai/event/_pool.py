"""Message and call pool deduplication for eval samples.

Design note — hash-based dedup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pool dedup keys on a murmur3 hash of the canonical JSON serialisation of
each ChatMessage (pydantic field order; dict fields keep insertion order
through a serialize/parse round-trip, so rebuild-time hashes match),
excluding the ``id`` field so that messages with identical content but
different UUIDs are treated as duplicates.

The batch functions here (``condense_model_event_inputs`` /
``condense_model_event_calls``) hash every message and rely on a per-call
``id(obj)`` cache; that is O(N) only when a single call spans all events
(the final-log and recover paths). Per-event callers (the sample buffer
and the transcript store) must NOT call these one event at a time — that
is O(N²) in conversation length (each of the N model events carries the
full ~N-message history). They use the incremental indices in
``inspect_ai.event._pool_index`` instead, which resolve re-sent messages
by object identity / id-bucket equality and hash only genuinely new
content.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, TypeVar, cast

from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from inspect_ai._util.hash import mm3_hash
from inspect_ai.event._validate import validate_events
from inspect_ai.model._chat_message import ChatMessage

from ._event import Event
from ._model import ModelEvent


def materialize_pooled_events(
    events: Iterable[object],
    message_pool: list[ChatMessage],
    call_pool: list[JsonValue],
) -> list[Event]:
    materialized = validate_events(list(events))
    materialized = resolve_model_event_inputs(materialized, message_pool)
    return resolve_model_event_calls(materialized, call_pool)


def _msg_hash(msg: ChatMessage) -> str:
    # Hash pydantic's canonical serialization directly (field order is
    # class-definition order; dict fields keep insertion order through a
    # serialize/parse round-trip, so rebuild-time hashes match). A dict
    # with different key insertion order hashes differently — that only
    # costs a duplicate pool entry, never wrong dedup.
    return mm3_hash(msg.model_dump_json(exclude={"id"}))


def _msg_pool_jsonable(msg: ChatMessage) -> JsonValue:
    """Jsonable form of a message-pool row (serialize with `_msg_pool_json`)."""
    return cast(
        JsonValue, to_jsonable_python(msg, exclude_none=True, fallback=lambda _: None)
    )


def _msg_pool_json(message_jsonable: JsonValue) -> str:
    """Serialize a message-pool row for storage.

    Owns the hash↔storage round-trip invariant: stored bytes must re-parse
    to a message whose `_msg_hash` equals the hash stored beside them.
    `_msg_hash` hashes insertion-order serialization, so storage must
    preserve insertion order too — never ``sort_keys=True``, which would
    reorder dict fields (tool-call arguments, metadata) and make re-seeded
    rows miss their own hash, duplicating pool entries on every resume.
    """
    return json.dumps(message_jsonable)


def _call_hash(call_msg: JsonValue) -> str:
    return mm3_hash(json.dumps(call_msg, sort_keys=True))


def _call_pool_json(call_msg: JsonValue) -> str:
    """Serialize a call-pool row for storage.

    Owns the hash↔storage round-trip invariant for the call pool: stored
    bytes must re-hash (via `_call_hash` after re-parse) to the hash stored
    beside them. `_call_hash` sorts keys, so storage sorts keys too.
    """
    return json.dumps(call_msg, sort_keys=True)


def _build_msg_index(pool: list[ChatMessage]) -> dict[str, int]:
    """Build hash -> pool index mapping, matching condense_model_event_inputs logic."""
    index: dict[str, int] = {}
    for i, msg in enumerate(pool):
        index[_msg_hash(msg)] = i
    return index


def _build_call_index(pool: list[JsonValue]) -> dict[str, int]:
    """Build hash -> pool index mapping, matching condense_model_event_calls logic."""
    index: dict[str, int] = {}
    for i, call_msg in enumerate(pool):
        index[_call_hash(call_msg)] = i
    return index


def condense_model_event_inputs(
    events: Sequence[Event],
    next_index: int,
    msg_index: Mapping[str, int],
) -> tuple[list[Event], dict[str, int], list[tuple[str, ChatMessage]]]:
    """Replace ModelEvent.input with message_pool references.

    Assigns each unique ChatMessage a position starting at ``next_index``
    and replaces ModelEvent inputs with range-encoded input_refs into a
    pool. Callers that need the pool list must rebuild it from
    ``new_entries`` (in order of appearance).

    See module docstring for the hash-based dedup strategy.

    Args:
        events: Events to condense.
        next_index: The pool position assigned to the first new unique
            message, typically the current pool length for callers carrying
            an existing pool.
        msg_index: Existing hash → pool-index map carried forward across
            calls.

    Returns:
        A tuple of (condensed events, updated index, new entries
        appended this call as ``(hash, msg)`` pairs in pool-position
        order).
    """
    index = dict(msg_index)
    obj_id_cache: dict[int, str] = {}
    new_entries: list[tuple[str, ChatMessage]] = []
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent):
            if event.input_refs is not None and not event.input:
                result.append(event)
                continue
            if event.input:
                raw_indices: list[int] = []
                for msg in event.input:
                    obj_key = id(msg)
                    h = obj_id_cache.get(obj_key) or obj_id_cache.setdefault(
                        obj_key, _msg_hash(msg)
                    )
                    if h not in index:
                        index[h] = next_index + len(new_entries)
                        new_entries.append((h, msg))
                    raw_indices.append(index[h])
                event = event.model_copy(
                    update={"input": [], "input_refs": _compress_refs(raw_indices)}
                )
        result.append(event)
    return result, index, new_entries


# Known keys for messages array in provider wire formats
_CALL_MESSAGE_KEYS: Final = ("messages", "contents", "input", "inputs")


def _compress_refs(indices: list[int]) -> list[tuple[int, int]]:
    """Compress contiguous int indices into range-encoded refs.

    Every element is a ``(start, end_exclusive)`` range pair.

    Examples::

        [0,1,2,3]   -> [(0,4)]
        [0,3,4,5,9] -> [(0,1),(3,6),(9,10)]
        [2,5,8]     -> [(2,3),(5,6),(8,9)]
        [3,4]       -> [(3,5)]
    """
    if not indices:
        return []
    result: list[tuple[int, int]] = []
    start = indices[0]
    end_exclusive = start + 1
    for i in indices[1:]:
        if i == end_exclusive:
            end_exclusive += 1
        else:
            result.append((start, end_exclusive))
            start = i
            end_exclusive = i + 1
    result.append((start, end_exclusive))
    return result


_T = TypeVar("_T")


def _expand_refs(
    refs: list[tuple[int, int]],
    pool: list[_T],
) -> list[_T]:
    """Expand range-encoded refs against a pool.

    Each element is ``(start, end_exclusive)``: yields ``pool[start:end_exclusive]``.
    """
    result: list[_T] = []
    for start, end_exclusive in refs:
        result.extend(pool[start:end_exclusive])
    return result


def condense_model_event_calls(
    events: Sequence[Event],
    next_index: int,
    call_index: Mapping[str, int],
) -> tuple[list[Event], dict[str, int], list[tuple[str, JsonValue]]]:
    """Replace call.request messages with call_pool references.

    Assigns each unique call message a position starting at ``next_index``
    and replaces ``event.call.request[<messages_key>]`` with range-encoded
    ``call_refs``. Callers that need the pool list must rebuild it from
    ``new_entries``.

    Args:
        events: Events to condense.
        next_index: The pool position assigned to the first new unique
            call message, typically the current pool length for callers
            carrying an existing pool.
        call_index: Existing hash → pool-index map.

    Returns:
        A tuple of (condensed events, updated index, new entries
        appended this call as ``(hash, msg)`` pairs in pool-position
        order).
    """
    index = dict(call_index)
    new_entries: list[tuple[str, JsonValue]] = []
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent) and event.call:
            if event.call.call_refs is not None:
                result.append(event)
                continue
            msg_key = next(
                (k for k in _CALL_MESSAGE_KEYS if k in event.call.request), None
            )
            msgs = event.call.request.get(msg_key) if msg_key else None
            if msgs and isinstance(msgs, list):
                raw_indices: list[int] = []
                for msg in msgs:
                    h = _call_hash(msg)
                    if h not in index:
                        index[h] = next_index + len(new_entries)
                        new_entries.append((h, msg))
                    raw_indices.append(index[h])
                new_request = {
                    k: v for k, v in event.call.request.items() if k != msg_key
                }
                new_call = event.call.model_copy(
                    update={
                        "request": new_request,
                        "call_refs": _compress_refs(raw_indices),
                        "call_key": msg_key,
                    }
                )
                event = event.model_copy(update={"call": new_call})
        result.append(event)
    return result, index, new_entries


def resolve_model_event_calls(
    events: list[Event],
    call_pool: list[JsonValue],
) -> list[Event]:
    """Restore call.request messages from call_pool references."""
    if not call_pool:
        return events
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent) and event.call and event.call.call_refs:
            msgs = _expand_refs(event.call.call_refs, call_pool)
            msg_key = event.call.call_key or "messages"
            new_request = dict(event.call.request)
            new_request[msg_key] = msgs
            new_call = event.call.model_copy(
                update={
                    "request": new_request,
                    "call_refs": None,
                    "call_key": None,
                }
            )
            event = event.model_copy(update={"call": new_call})
        result.append(event)
    return result


def resolve_model_event_inputs(
    events: list[Event],
    message_pool: list[ChatMessage],
) -> list[Event]:
    """Resolve ModelEvent input_refs back to full input lists."""
    if not message_pool:
        return events
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent) and event.input_refs is not None:
            resolved_input = _expand_refs(event.input_refs, message_pool)
            event = event.model_copy(
                update={"input": resolved_input, "input_refs": None}
            )
        result.append(event)
    return result
