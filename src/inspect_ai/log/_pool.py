"""Message and call pool deduplication for eval samples.

Design note — hash-based dedup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pool dedup keys on a murmur3 hash of the full sorted-keys JSON serialisation
of each ChatMessage.  This is correct-by-construction: identical content
always produces the same hash, and mutated content (even with a stale
``msg.id``) produces a different hash.

The theoretical cost is O(N²) serialisations per sample (each of the N
model events carries the full conversation history of ~N messages).
In practice an ``id(obj)`` → hash cache avoids re-serialising the same
Python object, bringing the common case back to O(N) while remaining
correct even when users mutate objects (same object identity = same
content by definition).
"""

import json
from collections.abc import Mapping, Sequence
from typing import Final, TypeVar

from pydantic import JsonValue

from inspect_ai._util.hash import mm3_hash
from inspect_ai.model._chat_message import ChatMessage

from ..event._event import Event
from ..event._model import ModelEvent
from ._log import EvalSample


def _msg_hash(msg: ChatMessage) -> str:
    """Compute a content hash for dedup keying."""
    return mm3_hash(json.dumps(json.loads(msg.model_dump_json()), sort_keys=True))


def _build_msg_index(pool: list[ChatMessage]) -> dict[str, int]:
    """Build msg_id -> pool index mapping, matching condense_model_event_inputs logic."""
    index: dict[str, int] = {}
    for i, msg in enumerate(pool):
        index[_msg_hash(msg)] = i
    return index


def _build_call_index(pool: list[JsonValue]) -> dict[str, int]:
    """Build hash -> pool index mapping, matching condense_model_event_calls logic."""
    index: dict[str, int] = {}
    for i, call_msg in enumerate(pool):
        index[mm3_hash(json.dumps(call_msg, sort_keys=True))] = i
    return index


def condense_model_event_inputs(
    events: Sequence[Event],
    message_pool: Sequence[ChatMessage],
    msg_index: Mapping[str, int],
) -> tuple[list[Event], list[ChatMessage]]:
    """Replace ModelEvent.input with message_pool references.

    Collects all messages from ModelEvent inputs into a message pool
    and replaces each ModelEvent's input with range-encoded input_refs.

    See module docstring for the hash-based dedup strategy.

    Returns:
        A tuple of (condensed events, message pool).
    """
    pool = list(message_pool)
    index = dict(msg_index)
    obj_id_cache: dict[int, str] = {}
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent):
            if event.input_refs is not None and not event.input:
                # Already condensed — preserve existing refs
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
                        index[h] = len(pool)
                        pool.append(msg)
                    raw_indices.append(index[h])
                event = event.model_copy(
                    update={"input": [], "input_refs": _compress_refs(raw_indices)}
                )
        result.append(event)
    return result, pool


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
    call_pool: Sequence[JsonValue],
    call_index: Mapping[str, int],
) -> tuple[list[Event], list[JsonValue]]:
    """Replace call.request messages with call_pool references.

    Returns:
        A tuple of (condensed events, call pool).
    """
    pool = list(call_pool)
    index = dict(call_index)
    result: list[Event] = []
    for event in events:
        if isinstance(event, ModelEvent) and event.call:
            if event.call.call_refs is not None:
                # Already condensed — preserve existing refs
                result.append(event)
                continue
            msg_key = next(
                (k for k in _CALL_MESSAGE_KEYS if k in event.call.request), None
            )
            msgs = event.call.request.get(msg_key) if msg_key else None
            if msgs and isinstance(msgs, list):
                raw_indices: list[int] = []
                for msg in msgs:
                    h = mm3_hash(json.dumps(msg, sort_keys=True))
                    if h not in index:
                        index[h] = len(pool)
                        pool.append(msg)
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
    return result, pool


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


def resolve_sample_message_pool(sample: EvalSample) -> EvalSample:
    """Resolve message pool references in model events.

    Always called on read to ensure ModelEvent.input is populated,
    regardless of the resolve_attachments setting.
    """
    if not sample.message_pool and not sample.call_pool:
        return sample
    resolved_events = resolve_model_event_inputs(sample.events, sample.message_pool)
    resolved_events = resolve_model_event_calls(resolved_events, sample.call_pool)
    return sample.model_copy(
        update={
            "events": resolved_events,
            "message_pool": [],
            "call_pool": [],
        }
    )
