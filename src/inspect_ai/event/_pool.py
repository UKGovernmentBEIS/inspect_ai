"""Message and call pool deduplication for eval samples.

Design note — occurrence-keyed dedup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pool positions identify logical *occurrences* of a message in the
conversation, not merely content. The batch functions here
(``condense_model_event_inputs`` / ``condense_model_event_calls``)
mirror the per-event helper in ``inspect_ai.event._pool_index``: the
previous event's input list and assigned positions are carried across
the event loop, and each event's longest shared prefix (object identity,
then equality) reuses those positions directly. When an event purely
appends to the previous one, the suffix messages are new occurrences and
mint fresh per-occurrence rows without consulting the content-hash index
— otherwise a loop emitting identical content each turn would map its
history onto alternating positions, making the range-compressed refs
quadratic in turns. Only prefix-*break* paths (first event, trim,
compaction, fresh-id-rebuilt histories) fall back to content dedup,
keyed on a murmur3 hash of the canonical JSON serialisation of each
ChatMessage (pydantic field order; dict fields keep insertion order
through a serialize/parse round-trip, so rebuild-time hashes match),
excluding the ``id`` field so that messages with identical content but
different UUIDs are treated as duplicates.

``condense_model_event_inputs`` additionally keeps a per-call ``id(obj)``
→ position cache, so re-sent message objects skip hashing entirely; that
is O(N) only when a single call spans all events (the final-log and
recover paths). Per-event callers (the sample buffer and the transcript
store) must NOT call these one event at a time — that is O(N²) in
conversation length (each of the N model events carries the full
~N-message history). They use the incremental indices in
``inspect_ai.event._pool_index`` instead, which resolve re-sent messages
by object identity / id-bucket equality and hash only genuinely new
content.
"""

import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, TypeVar, cast

from pydantic import BaseModel, JsonValue
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


def _strict_eq(a: object, b: object) -> bool:
    """Equality that distinguishes values with different JSON serializations.

    Python ``==`` conflates values the pool hashes distinguish: ``0 == 0.0``
    and ``True == 1``, but ``json.dumps`` emits different bytes for each, so
    ``_msg_hash``/``_call_hash`` differ. An ``==``-based merge of such values
    would reuse a pool entry whose stored bytes round-trip to the *other*
    value — silent data corruption. This comparison requires matching types
    for scalars (recursing into models, dataclasses, dicts, and lists), so a
    merge implies identical serialization.

    Lives here (not ``_pool_index``) because both the batch condense
    functions below and the per-event indices need it, and ``_pool_index``
    already imports from this module.
    """
    if a is b:
        return True
    ta, tb = type(a), type(b)
    if ta is not tb:
        return False
    if isinstance(a, BaseModel):
        return _strict_eq(a.__dict__, b.__dict__)  # type: ignore[attr-defined]
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        return _strict_eq(vars(a), vars(b))
    if ta is dict:
        assert isinstance(a, dict) and isinstance(b, dict)
        if len(a) != len(b):
            return False
        sentinel = object()
        for k, v in a.items():
            other = b.get(k, sentinel)
            if other is sentinel or not _strict_eq(v, other):
                return False
            # dict lookup matches keys by ==, which conflates 0/0.0 and
            # True/1 on the key axis just like values ({0: x} and {0.0: x}
            # serialize to different JSON); str keys (the JSON-bound common
            # case) cannot ==-collide across types, so only non-str keys
            # need their counterpart's type checked
            if type(k) is not str and not any(
                bk == k and type(bk) is type(k) for bk in b
            ):
                return False
        return True
    if ta is list or ta is tuple:
        assert isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
        return len(a) == len(b) and all(_strict_eq(x, y) for x, y in zip(a, b))
    return a == b


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
    """Build hash -> first-occurrence pool index, matching condense_model_event_inputs logic."""
    index: dict[str, int] = {}
    for i, msg in enumerate(pool):
        index.setdefault(_msg_hash(msg), i)
    return index


def _build_call_index(pool: list[JsonValue]) -> dict[str, int]:
    """Build hash -> first-occurrence pool index, matching condense_model_event_calls logic."""
    index: dict[str, int] = {}
    for i, call_msg in enumerate(pool):
        index.setdefault(_call_hash(call_msg), i)
    return index


def condense_model_event_inputs(
    events: Sequence[Event],
    next_index: int,
    msg_index: Mapping[str, int],
) -> tuple[list[Event], dict[str, int], list[tuple[str, ChatMessage]]]:
    """Replace ModelEvent.input with message_pool references.

    Assigns each message occurrence a position starting at ``next_index``
    and replaces ModelEvent inputs with range-encoded input_refs into a
    pool. Callers that need the pool list must rebuild it from
    ``new_entries`` (in order of appearance).

    See module docstring for the occurrence-keyed dedup strategy.

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
    # object identity -> assigned position (re-sent objects skip hashing)
    obj_pos_cache: dict[int, int] = {}
    new_entries: list[tuple[str, ChatMessage]] = []
    prev_input: list[ChatMessage] = []
    prev_indices: list[int] = []
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent):
            if event.input_refs is not None and not event.input:
                result.append(event)
                continue
            if event.input:
                # longest prefix of the previous event's input (identity,
                # then strict equality) — the same occurrence-identity
                # mechanism as condense_model_event_with_indices
                raw_indices: list[int] = []
                for msg, prev_msg, prev_index in zip(
                    event.input, prev_input, prev_indices
                ):
                    if msg is prev_msg or (
                        msg == prev_msg and _strict_eq(msg, prev_msg)
                    ):
                        raw_indices.append(prev_index)
                    else:
                        break
                pure_append = 0 < len(prev_input) == len(raw_indices)
                for msg in event.input[len(raw_indices) :]:
                    obj_key = id(msg)
                    pos = obj_pos_cache.get(obj_key)
                    if pos is None:
                        h = _msg_hash(msg)
                        pos = None if pure_append else index.get(h)
                        if pos is None:
                            pos = next_index + len(new_entries)
                            if h not in index:
                                index[h] = pos
                            new_entries.append((h, msg))
                        obj_pos_cache[obj_key] = pos
                    raw_indices.append(pos)
                prev_input = list(event.input)
                prev_indices = list(raw_indices)
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

    Assigns each call-message occurrence a position starting at
    ``next_index`` and replaces ``event.call.request[<messages_key>]``
    with range-encoded ``call_refs``. Callers that need the pool list
    must rebuild it from ``new_entries``.

    See module docstring for the occurrence-keyed dedup strategy.

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
    prev_msgs: list[JsonValue] = []
    prev_indices: list[int] = []
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
                for msg, prev_msg, prev_index in zip(msgs, prev_msgs, prev_indices):
                    # _strict_eq, not ==: a prefix element drifting 0 -> 0.0
                    # or True -> 1 is python-equal but hashes differently;
                    # reusing the pool index would round-trip the other value
                    if _strict_eq(msg, prev_msg):
                        raw_indices.append(prev_index)
                    else:
                        break
                pure_append = 0 < len(prev_msgs) == len(raw_indices)
                for msg in msgs[len(raw_indices) :]:
                    h = _call_hash(msg)
                    pos = None if pure_append else index.get(h)
                    if pos is None:
                        pos = next_index + len(new_entries)
                        if h not in index:
                            index[h] = pos
                        new_entries.append((h, msg))
                    raw_indices.append(pos)
                prev_msgs = list(msgs)
                prev_indices = list(raw_indices)
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
