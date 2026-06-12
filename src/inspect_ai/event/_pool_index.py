"""In-memory acceleration indices for message/call pool dedup.

These make per-event condensing cost proportional to the *new* messages
in each event rather than the full conversation history:

- ``MessagePoolIndex`` buckets on ``ChatMessage.id`` (a random UUID) and
  verifies candidates by object identity, then content equality. Agents
  reuse the same message objects across turns, so the identity fast path
  hits for the entire shared history without any serialization. It also
  retains the previous event's input list and pool positions so the next
  event's shared prefix can be matched element-by-element.
- ``CallPoolIndex`` exploits the append-mostly structure of provider wire
  requests: the previous event's message list is retained and the shared
  prefix matched by plain equality; only the divergent suffix is hashed.
  The prefix scan is O(shared-history) comparisons with a small constant
  (no serialization or allocation); it is not O(new) like the message
  index, but in practice most events share a long stable prefix so the
  total work per event stays low.

Pool positions are occurrence-keyed: a position identifies a logical
occurrence of a message in the conversation, not merely its content.
Re-sends of the same occurrence resolve via the prefix match or the
identity buckets; only prefix-*break* paths (first event, trim,
compaction, resume, fresh-id-rebuilt histories) consult content hashes.
When an event purely appends to the previous one, suffix messages mint
fresh per-occurrence rows even if their content duplicates an earlier
row — otherwise a loop emitting identical content each turn would map
its history onto alternating positions, making the range-compressed
refs quadratic in turns.

Correctness never depends on these assumptions: a merge happens only when
serialization-equivalent equality (``_strict_eq``; plain ``==`` would
conflate ``0``/``0.0`` and ``True``/``1``, which hash differently) or hash
equality confirms it. The worst case is extra hashing, never wrong dedup. Indices hold pre-walk
objects (what callers re-send across events); hashes are of the walked
form (what resume/recover paths recompute from stored pool entries).
Both indices support ``mark()``/``restore()`` so callers can unwind
in-memory state when a database transaction rolls back. The restore
contract: ``restore(mark)`` guarantees the index references no pool
position added after ``mark``. Correctness-bearing hash entries are
undone precisely (a stale entry yields dangling refs or, in the buffer,
misaligned ``size``-derived positions); accelerator state may instead be
conservatively dropped — a lookup miss is always safe, a stale entry
never is. The message buckets get precise undo because the same log that
the hash entries need carries them for free; the call prefix state is
dropped.

Messages containing a content string over ``_BUCKET_CONTENT_LIMIT``
(base64 media payloads) are never bucketed: bucketed pre-walk objects are
pinned for the sample's lifetime, which would re-accumulate exactly the
memory that bounded transcripts (``INSPECT_TRANSCRIPT_BOUNDED``) evict.
Such messages dedup via the hash path instead, costing one re-walk and
re-hash per event that re-sends them — cheap, because their walked form
replaces payloads with short attachment refs.

Note on in-place mutation: a ``ChatMessage`` mutated after being pooled
identity-hits on the index and resolves to its first-pooled form. This
is consistent with the prior ``id(obj)``-cache behavior documented in
``_pool.py`` — mutation aliases every holder of the object, so no
distinct prior value exists.
"""

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, JsonValue

from inspect_ai.model._chat_message import ChatMessage

from . import (
    _pool,  # accessed as module attributes so monkeypatching _pool._msg_hash is visible here
)
from ._model import ModelEvent
from ._pool import _CALL_MESSAGE_KEYS, _compress_refs, _strict_eq

_BUCKET_CONTENT_LIMIT = 64 * 1024
"""Max single content-string length (bytes) for a message to be bucketed.

Separates the two observed content populations by orders of magnitude:
text/tool content strings sit at p99 ≈ 8.5KB (worst observed outlier
94KB, whose un-bucketed re-hash costs ~9µs/event), while base64 media
payloads start around 100KB and are typically 1-5MB. Anything above the
limit is media-scale and must not be pinned in memory; anything below is
cheap to pin and benefits from the equality fast path.
"""


_MAX_SCAN_DEPTH = 20
"""Recursion bound for the heavy-string scan.

Real message structures are a handful of levels deep; the bound exists
for arbitrary ``metadata``/``ContentData.data`` values, which agent and
tool code can populate with cyclic or pathologically nested structures.
Capping out reports heavy — the safe direction (the message just isn't
bucketed).
"""


def _has_heavy_str(value: object, depth: int = 0) -> bool:
    """Whether any string within a value exceeds ``_BUCKET_CONTENT_LIMIT``.

    Recurses into models, dataclasses, dicts, and lists, so every
    payload-bearing field is covered uniformly (content blocks,
    ``ContentData.data``, tool-call arguments and views, metadata)
    without enumerating fields that would have to be kept in sync.
    Short-circuits on the first heavy string and stops descending at
    ``_MAX_SCAN_DEPTH`` (reporting heavy), so the scan is cheap on the
    hot path and safe on cyclic values.
    """
    if depth >= _MAX_SCAN_DEPTH:
        return True
    if isinstance(value, str):
        return len(value) > _BUCKET_CONTENT_LIMIT
    if isinstance(value, BaseModel):
        return _has_heavy_str(value.__dict__, depth + 1)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # vars() not dataclasses.asdict(): asdict deep-copies, which would
        # defeat the cheap scan on multi-MB payloads
        return _has_heavy_str(vars(value), depth + 1)
    if isinstance(value, dict):
        return any(_has_heavy_str(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_heavy_str(v, depth + 1) for v in value)
    return False


class MessagePoolIndex:
    """Id-bucketed, identity-first lookup index for ChatMessage objects.

    Buckets messages by their ``id`` field (a random UUID) and verifies
    candidates first by object identity, then by content equality. This
    allows O(1)-per-message lookup when agents reuse the same objects
    across turns.

    A walked-form content hash is also maintained so callers can locate
    entries reconstructed from storage (no object reuse) via
    ``get_by_hash``.

    Like ``CallPoolIndex``, the previous event's input list and its pool
    positions are retained (``set_prev``) so the next event's shared
    prefix can be matched element-by-element (``match_prefix``) — this
    keeps positions monotone for duplicate-content occurrences instead of
    collapsing them to the first hash hit.

    ``size`` counts pool *rows* recorded (occurrence rows may share a
    hash), not distinct hashes, so buffer callers can derive the next
    row position from it.

    Supports ``mark()``/``restore()`` to unwind state when a surrounding
    database transaction rolls back.
    """

    def __init__(self) -> None:
        # msg.id -> [(pre-walk message, pool index)]
        self._buckets: dict[str, list[tuple[ChatMessage, int]]] = {}
        # walked-form content hash -> pool index (first occurrence wins)
        self._hash_index: dict[str, int] = {}
        # pool rows recorded (NOT distinct hashes: occurrence rows share hashes)
        self._size: int = 0
        # undo log: (bucket key appended to or None, hash added or None, row counted)
        self._log: list[tuple[str | None, str | None, bool]] = []
        # previous event's pre-walk input and its pool positions
        self._prev_msgs: list[ChatMessage] = []
        self._prev_indices: list[int] = []

    @property
    def size(self) -> int:
        """Number of pool rows recorded via ``add(..., new_entry=True)``.

        Meaningful as a position source only when every counted add
        corresponds to exactly one persisted row (the buffer's contract).
        """
        return self._size

    @property
    def prev_len(self) -> int:
        """Length of the previously recorded input (0 if none recorded)."""
        return len(self._prev_msgs)

    def match_prefix(self, msgs: Sequence[ChatMessage]) -> list[int]:
        """Pool indices for the longest shared prefix with the previous input.

        Elements match by object identity first, then pydantic equality
        (which includes ``id``, so fresh-id re-sends deliberately miss)
        confirmed by ``_strict_eq`` (a ``0``-vs-``0.0`` or ``True``-vs-``1``
        drift is python-equal but serializes and hashes differently).
        Comparison stops at the first non-matching element.

        Args:
            msgs: New event's input messages (pre-walk).

        Returns:
            Pool indices for the matched prefix; empty if no previous input
            was recorded or the first element differs.
        """
        indices: list[int] = []
        for msg, prev_msg, prev_index in zip(msgs, self._prev_msgs, self._prev_indices):
            if msg is prev_msg or (msg == prev_msg and _strict_eq(msg, prev_msg)):
                indices.append(prev_index)
            else:
                break
        return indices

    def set_prev(self, msgs: Sequence[ChatMessage], indices: Sequence[int]) -> None:
        """Record the input just condensed for prefix-matching the next event.

        Copies both sequences shallowly (same aliasing contract as
        ``CallPoolIndex.set_prev``: message values are shared, and in-place
        mutation aliases every holder, which is already documented behavior).

        Args:
            msgs: Pre-walk input message list.
            indices: Corresponding pool indices, parallel to ``msgs``.
        """
        self._prev_msgs = list(msgs)
        self._prev_indices = list(indices)

    def get(self, msg: ChatMessage) -> int | None:
        """Fast-path lookup without serialization (identity, then equality).

        The equality arm runs pydantic ``==`` first (cheap C-level reject)
        and confirms prospective merges with ``_strict_eq``, which a
        ``0``-vs-``0.0`` or ``True``-vs-``1`` difference in metadata or
        tool-call arguments fails even though ``==`` passes.

        Args:
            msg: The message to look up.

        Returns:
            Pool index if found, ``None`` otherwise. Returns ``None`` when
            ``msg.id`` is ``None`` (no bucket can be checked).
        """
        if msg.id is None:
            return None
        for stored, index in self._buckets.get(msg.id, ()):
            if stored is msg or (stored == msg and _strict_eq(stored, msg)):
                return index
        return None

    def get_by_hash(self, hash_value: str) -> int | None:
        """Look up a pool index by walked-form content hash.

        Args:
            hash_value: Walked-form hash string.

        Returns:
            Pool index if found, ``None`` otherwise.
        """
        return self._hash_index.get(hash_value)

    def add(
        self, msg: ChatMessage, hash_value: str, index: int, *, new_entry: bool = True
    ) -> None:
        """Record a pool entry (or accelerator-only lookup state).

        Messages with a content string over ``_BUCKET_CONTENT_LIMIT`` are
        recorded in the hash index only (see module docstring): bucketing
        would pin their payload in memory for the sample's lifetime.

        Args:
            msg: Pre-walk message object.
            hash_value: Walked-form content hash.
            index: Pool index for this entry.
            new_entry: ``True`` when this call corresponds to a newly
                persisted pool row (counted in ``size``); ``False`` for
                accelerator-only registration of an existing row
                (resume/seeding paths).
        """
        bucket_key = msg.id if not _has_heavy_str(msg.__dict__) else None
        if bucket_key is not None:
            self._buckets.setdefault(bucket_key, []).append((msg, index))
        hash_added: str | None = None
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            hash_added = hash_value
        if new_entry:
            self._size += 1
        if bucket_key is not None or hash_added is not None or new_entry:
            self._log.append((bucket_key, hash_added, new_entry))

    def add_hash_only(self, hash_value: str, index: int) -> None:
        """Register an existing row's hash without an object to bucket.

        Used when seeding from storage where only walked JSON is available.
        Does not count toward ``size``.

        Args:
            hash_value: Walked-form content hash.
            index: Pool index for this entry. Ignored if the hash is
                already registered (first occurrence wins).
        """
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            self._log.append((None, hash_value, False))

    def mark(self) -> int:
        """Return a mark for later ``restore()``.

        Returns:
            Opaque integer mark representing the current index state.
        """
        return len(self._log)

    def restore(self, mark: int) -> None:
        """Undo all ``add()`` and ``add_hash_only()`` calls made since ``mark()``.

        Correctness-bearing state (hashes, row count) is rewound precisely;
        the prefix-match state is accelerator-only and dropped instead
        (same rationale as ``CallPoolIndex.restore``).

        Args:
            mark: Value previously returned by ``mark()``.
        """
        while len(self._log) > mark:
            bucket_key, hash_added, row_added = self._log.pop()
            if bucket_key is not None:
                bucket = self._buckets[bucket_key]
                bucket.pop()
                if not bucket:
                    del self._buckets[bucket_key]
            if hash_added is not None:
                del self._hash_index[hash_added]
            if row_added:
                self._size -= 1
        self._prev_msgs = []
        self._prev_indices = []


class CallPoolIndex:
    """Prefix-diff lookup index for provider wire-request message lists.

    Wire-format call messages have no stable ids and no object reuse, so
    instead this index exploits the append-only growth pattern: the
    previous event's message list is retained and compared element-by-element
    against new requests; the matching prefix is reused directly.

    A hash index covers the non-prefix tail so individual messages can still
    be deduplicated across events.

    ``size`` counts pool *rows* recorded (occurrence rows may share a
    hash), not distinct hashes, so buffer callers can derive the next
    row position from it.

    Supports ``mark()``/``restore()`` to unwind state when a surrounding
    database transaction rolls back.
    """

    def __init__(self) -> None:
        # walked-form content hash -> pool index (first occurrence wins)
        self._hash_index: dict[str, int] = {}
        # pool rows recorded (NOT distinct hashes)
        self._size: int = 0
        # previous event's pre-walk wire messages and their pool indices
        self._prev_msgs: list[JsonValue] = []
        self._prev_indices: list[int] = []
        # undo log: (hash added or None, row counted)
        self._log: list[tuple[str | None, bool]] = []

    @property
    def size(self) -> int:
        """Number of pool rows recorded via ``add_hash(..., new_entry=True)``.

        Meaningful as a position source only when every counted add
        corresponds to exactly one persisted row (the buffer's contract).
        """
        return self._size

    @property
    def prev_len(self) -> int:
        """Length of the previously recorded request (0 if none recorded)."""
        return len(self._prev_msgs)

    def match_prefix(self, msgs: Sequence[JsonValue]) -> list[int]:
        """Pool indices for the longest shared prefix with the previous request.

        Comparison stops at the first element that differs from the
        corresponding element in the previous request; later elements
        are ignored even if equal.

        Args:
            msgs: New request's message list (pre-walk wire format).

        Returns:
            List of pool indices for the matched prefix. Empty if no prefix
            matches or no previous request has been recorded.
        """
        indices: list[int] = []
        for msg, prev_msg, prev_index in zip(msgs, self._prev_msgs, self._prev_indices):
            # _strict_eq, not ==: a prefix element drifting 0 -> 0.0 or
            # True -> 1 is python-equal but serializes (and hashes)
            # differently; reusing the pool index would round-trip the
            # other value
            if not _strict_eq(msg, prev_msg):
                break
            indices.append(prev_index)
        return indices

    def get_by_hash(self, hash_value: str) -> int | None:
        """Look up a pool index by walked-form content hash.

        Args:
            hash_value: Walked-form hash string.

        Returns:
            Pool index if found, ``None`` otherwise.
        """
        return self._hash_index.get(hash_value)

    def add_hash(self, hash_value: str, index: int, *, new_entry: bool = True) -> None:
        """Record a pool entry by its walked-form hash.

        The hash index keeps the first occurrence's position; later
        occurrence rows still count toward ``size``.

        Args:
            hash_value: Walked-form content hash.
            index: Pool index for this entry.
            new_entry: ``True`` when this call corresponds to a newly
                persisted pool row; ``False`` for accelerator-only
                registration of an existing row (resume/seeding paths).
        """
        hash_added: str | None = None
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            hash_added = hash_value
        if new_entry:
            self._size += 1
        if hash_added is not None or new_entry:
            self._log.append((hash_added, new_entry))

    def set_prev(self, msgs: Sequence[JsonValue], indices: Sequence[int]) -> None:
        """Record the request just condensed for prefix-matching the next one.

        Copies both sequences shallowly, so callers may freely mutate the
        sequences themselves afterwards. The copy is shallow: message
        *values* are shared with the caller, and the next event's
        ``match_prefix`` compares against them — mutating one in place to
        equal new content would match the prefix against content that was
        never pooled at that position, returning a wrong pool index.

        Args:
            msgs: Pre-walk wire-format message list.
            indices: Corresponding pool indices, parallel to ``msgs``.
        """
        self._prev_msgs = list(msgs)
        self._prev_indices = list(indices)

    def mark(self) -> int:
        """Return a mark for later ``restore()``.

        Returns:
            Opaque integer mark representing the current index state.
        """
        return len(self._log)

    def restore(self, mark: int) -> None:
        """Drop all pool references recorded since ``mark()`` was obtained.

        Hash entries and the row count are undone precisely (a stale entry
        would make the retry skip an insert and emit dangling refs; a stale
        count misaligns buffer positions). The prefix-match state is
        accelerator-only, so it is dropped rather than rewound: the next
        event's prefix scan misses and falls through to hash dedup, which
        is always safe. Rewinding it would require holding a snapshot of
        ``_prev_msgs`` across the marked window, reintroducing aliasing to
        reason about for a path that only runs after a database
        transaction failure.

        Args:
            mark: Value previously returned by ``mark()``.
        """
        while len(self._log) > mark:
            hash_added, row_added = self._log.pop()
            if hash_added is not None:
                del self._hash_index[hash_added]
            if row_added:
                self._size -= 1
        self._prev_msgs = []
        self._prev_indices = []


def condense_model_event_with_indices(
    event: ModelEvent,
    *,
    messages: MessagePoolIndex,
    calls: CallPoolIndex,
    walk_message: Callable[[ChatMessage], ChatMessage],
    walk_call_message: Callable[[JsonValue], JsonValue],
    add_message: Callable[[str, ChatMessage], int],
    add_call: Callable[[str, JsonValue], int],
) -> ModelEvent:
    """Condense one ModelEvent against in-memory pool indices.

    Only messages not already indexed are walked, hashed, and persisted via
    ``add_message``/``add_call``; index-hit messages cost a bucket probe or a
    prefix comparison with no serialization.

    Args:
        event: The ModelEvent to condense.
        messages: In-memory index for ``ChatMessage`` objects.
        calls: In-memory index for provider wire-request message lists.
        walk_message: Applies the attachment-ref transform to a ChatMessage
            before hashing; the result is what ``add_message`` receives.
        walk_call_message: Applies the attachment-ref transform to a raw
            wire-format message value before hashing; the result is what
            ``add_call`` receives.
        add_message: Must persist the walked ChatMessage and return its pool
            position (an integer row index within the caller's storage).
            Contract: each result is registered in ``messages`` before the
            next ``add_message`` call, so callers may derive positions from
            ``messages.size`` (the buffer does).
        add_call: Must persist the walked wire-format message value and return
            its pool position (an integer row index within the caller's
            storage). Same ordering contract as ``add_message``, against
            ``calls.size``.

    Returns:
        A new ModelEvent with ``input``/``input_refs`` and/or
        ``call``/``call_refs`` updated to reference pool positions, or the
        original ``event`` unchanged if there was nothing to condense.

    Note:
        Atomicity: on exception, indices may already reference pool positions
        whose rows belong to the caller's open transaction. Callers must call
        ``messages.mark()`` and ``calls.mark()`` before a batch and
        ``messages.restore()``/``calls.restore()`` on rollback to keep the
        in-memory indices consistent with storage.

        Occurrence identity: pool positions identify logical occurrences,
        not just content. When an event's input is a pure append of the
        previous event's input, the suffix messages are new occurrences and
        mint per-occurrence pool rows without consulting the content-hash
        index (which would map repeated content onto alternating positions,
        making the range-compressed refs quadratic across a long loop).
        Suffix rows are bucketed (the heavy-content gate still applies), so
        re-sends of those objects resolve by identity. A prefix break
        (first event, trim, compaction, resume, fresh-id-rebuilt histories)
        keeps content dedup — and there the original decision not to bucket
        hash-hit messages still applies: it avoids O(events × history)
        pinned objects for fresh-id scaffolds (bridge-style agents) where a
        hash hit would leave a useless bucket entry that could never
        produce a future identity hit.
    """
    update: dict[str, Any] = {}

    # Mirror condense_model_event_inputs guard ordering exactly:
    # passthrough if already condensed (refs set, input empty); skip if
    # input is empty (nothing to condense).
    if event.input_refs is not None and not event.input:
        pass
    elif event.input:
        raw_indices = messages.match_prefix(event.input)
        # 0 < prev_len guards the first-event/post-restore case (an empty
        # previous input must not classify as append); == len(raw_indices)
        # requires the FULL previous input to have matched. See the Note
        # in this function's docstring for the append/break semantics.
        pure_append = 0 < messages.prev_len == len(raw_indices)
        for msg in event.input[len(raw_indices) :]:
            index = messages.get(msg)
            if index is None:
                walked = walk_message(msg)
                msg_hash = _pool._msg_hash(walked)
                index = None if pure_append else messages.get_by_hash(msg_hash)
                if index is None:
                    index = add_message(msg_hash, walked)
                    messages.add(msg, msg_hash, index)
            raw_indices.append(index)
        messages.set_prev(event.input, raw_indices)
        update["input"] = []
        update["input_refs"] = _compress_refs(raw_indices)

    call = event.call
    if call is not None and call.call_refs is None:
        msg_key = next((k for k in _CALL_MESSAGE_KEYS if k in call.request), None)
        msgs = call.request.get(msg_key) if msg_key else None
        if msgs and isinstance(msgs, list):
            call_indices = calls.match_prefix(msgs)
            pure_append_calls = 0 < calls.prev_len == len(call_indices)
            for msg_value in msgs[len(call_indices) :]:
                walked_value = walk_call_message(msg_value)
                call_hash = _pool._call_hash(walked_value)
                call_index = None if pure_append_calls else calls.get_by_hash(call_hash)
                if call_index is None:
                    call_index = add_call(call_hash, walked_value)
                    calls.add_hash(call_hash, call_index)
                call_indices.append(call_index)
            calls.set_prev(msgs, call_indices)
            new_request = {k: v for k, v in call.request.items() if k != msg_key}
            update["call"] = call.model_copy(
                update={
                    "request": new_request,
                    "call_refs": _compress_refs(call_indices),
                    "call_key": msg_key,
                }
            )

    return event.model_copy(update=update) if update else event
