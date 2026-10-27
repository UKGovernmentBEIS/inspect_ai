"""In-memory acceleration indices for message/call pool dedup.

These make per-event condensing cost proportional to the *new* messages
in each event rather than the full conversation history:

- ``MessagePoolIndex`` buckets on ``ChatMessage.id`` (a random UUID) and
  verifies candidates by object identity, then content equality. Agents
  reuse the same message objects across turns, so the identity fast path
  hits for the entire shared history without any serialization.
- ``CallPoolIndex`` exploits the append-mostly structure of provider wire
  requests: recent request lineages are retained (see ``PrefixLineages``)
  and each new request takes the best prefix match among them; only the
  divergent suffix is hashed. Logged requests share message objects across
  calls (``CallMessageInterner``), so the prefix scan is a C-level list
  comparison that is mostly identity checks.

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
distinct prior value exists. The call index likewise retains the wire
message objects it condensed, which callers must not mutate in place.
"""

import dataclasses
import operator
from collections.abc import Callable, Sequence
from itertools import compress, count
from typing import Any, Final, TypeAlias

from pydantic import BaseModel, JsonValue

from inspect_ai._util.lineage import LineageMatch, PrefixLineages
from inspect_ai._util.lineage import strict_eq as _strict_eq
from inspect_ai.model._chat_message import ChatMessage

from . import (
    _pool,  # accessed as module attributes so monkeypatching _pool._msg_hash is visible here
)
from ._model import ModelEvent
from ._pool import (
    _CALL_MESSAGE_KEYS,
    _compress_refs,
)

_BUCKET_CONTENT_LIMIT = 256 * 1024
"""Max single content-string length (characters, not bytes: the payload class
this gate targets is base64, so the two coincide) for a message to be bucketed.

Set to include the largest observed text/tool content: typical agentic
evals sit at p99 ≈ 8.5KB, while long-conversation chat evals (e.g. the
incident workload behind this module) average ~54KB per message with a
tail crossing 100KB. Base64 media payloads start around 140KB for the
smallest useful image but are typically 1-5MB; the gate exists for the
multi-MB class, where pinning pre-walk objects for the sample's lifetime
re-accumulates the memory bounded transcripts evict. The cost of a
misclassification is bounded either way: an un-bucketed text message is
re-walked per event (~µs at these sizes); a pinned 200KB outlier is a
few hundred KB per unique message.
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

    Supports ``mark()``/``restore()`` to unwind state when a surrounding
    database transaction rolls back.
    """

    def __init__(self) -> None:
        # msg.id -> [(pre-walk message, pool index)]
        self._buckets: dict[str, list[tuple[ChatMessage, int]]] = {}
        # walked-form content hash -> pool index
        self._hash_index: dict[str, int] = {}
        # undo log: (bucket key appended to or None, hash added or None)
        self._log: list[tuple[str | None, str | None]] = []
        # the last resolved input's leading run of bucketed messages (pinned,
        # so identity stays meaningful) and their pool indices
        self._last_msgs: list[ChatMessage] = []
        self._last_indices: list[int] = []

    @property
    def size(self) -> int:
        """Number of distinct pool entries indexed."""
        return len(self._hash_index)

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
        return self.lookup(msg)[0]

    def lookup(self, msg: ChatMessage) -> tuple[int | None, bool]:
        """``get`` plus whether the hit was by object identity.

        Args:
            msg: The message to look up.

        Returns:
            Pool index (or ``None``) and whether it resolved by identity.
        """
        if msg.id is None:
            return None, False
        for stored, index in self._buckets.get(msg.id, ()):
            if stored is msg:
                return index, True
            # a value whose __eq__ doesn't return a bool (numpy array, pandas
            # Series, torch tensor) makes the comparison raise: a miss, so
            # the hash lookup decides
            try:
                if stored == msg and _strict_eq(stored, msg):
                    return index, False
            except Exception:
                pass
        return None, False

    def match_identity_run(self, msgs: Sequence[ChatMessage]) -> list[int]:
        """Pool indices of the leading ``msgs`` recorded by ``set_identity_run``.

        A position matches only when it holds the very object recorded
        there, which ``lookup`` would resolve by identity to the same index.
        Agents re-send the previous turn's message objects, so the shared
        history matches without a per-message bucket probe.

        Args:
            msgs: Message list about to be resolved.

        Returns:
            Pool indices for the matched leading run (possibly empty).
        """
        last = self._last_msgs
        n = next(
            compress(count(), map(operator.is_not, msgs, last)),
            min(len(msgs), len(last)),
        )
        return self._last_indices[:n]

    def set_identity_run(
        self, msgs: Sequence[ChatMessage], indices: Sequence[int], run: int
    ) -> None:
        """Record a resolved message list for ``match_identity_run``.

        Args:
            msgs: The resolved message list.
            indices: Pool index of each message, parallel to ``msgs``.
            run: Length of the leading run that resolves by identity.
        """
        self._last_msgs = list(msgs[:run])
        self._last_indices = list(indices[:run])

    def get_by_hash(self, hash_value: str) -> int | None:
        """Look up a pool index by walked-form content hash.

        Args:
            hash_value: Walked-form hash string.

        Returns:
            Pool index if found, ``None`` otherwise.
        """
        return self._hash_index.get(hash_value)

    def add(self, msg: ChatMessage, hash_value: str, index: int) -> bool:
        """Record a pool entry.

        Messages with a content string over ``_BUCKET_CONTENT_LIMIT`` are
        recorded in the hash index only (see module docstring): bucketing
        would pin their payload in memory for the sample's lifetime.

        Args:
            msg: Pre-walk message object.
            hash_value: Walked-form content hash.
            index: Pool index for this entry.

        Returns:
            Whether ``msg`` was bucketed (so ``lookup`` resolves it by identity).
        """
        bucket_key = (
            msg.id if msg.id is not None and not _has_heavy_str(msg.__dict__) else None
        )
        if bucket_key is not None:
            self._buckets.setdefault(bucket_key, []).append((msg, index))
        hash_added: str | None = None
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            hash_added = hash_value
        if bucket_key is not None or hash_added is not None:
            self._log.append((bucket_key, hash_added))
        return bucket_key is not None

    def mark(self) -> int:
        """Return a mark for later ``restore()``.

        Returns:
            Opaque integer mark representing the current index state.
        """
        return len(self._log)

    def restore(self, mark: int) -> None:
        """Undo all ``add()`` calls made since ``mark()`` was obtained.

        Args:
            mark: Value previously returned by ``mark()``.
        """
        self._last_msgs = []
        self._last_indices = []
        while len(self._log) > mark:
            bucket_key, hash_added = self._log.pop()
            if bucket_key is not None:
                bucket = self._buckets[bucket_key]
                bucket.pop()
                if not bucket:
                    del self._buckets[bucket_key]
            if hash_added is not None:
                del self._hash_index[hash_added]


_CALL_PREV_SLOTS: Final = 8
"""Retained request lineages per CallPoolIndex (see ``PrefixLineages``).

Two per concurrent generate stream (the raw request, and the
transcript-condensed form the same stream also notifies), so 8 cover ~4
interleaved streams.
"""


_CALL_PREV_MAX_IDLE: Final = 4 * _CALL_PREV_SLOTS
"""Prefix scans a lineage may go unmatched before it is dropped."""


PrefixMatch: TypeAlias = LineageMatch[None, int]
"""A ``match_prefix`` result (``entries`` are its pool indices), consumed by
the following ``set_prev``."""


class CallPoolIndex:
    """Prefix-diff lookup index for provider wire-request message lists.

    Wire requests grow by appending, so each new request is matched against
    recently condensed ones (see ``PrefixLineages``) and the shared leading
    run reuses their pool indices directly. Logged requests share message
    objects across calls (see ``CallMessageInterner``), so that comparison
    is mostly identity checks.

    A hash index covers the non-prefix tail so individual messages can still
    be deduplicated across events.

    Retained lineages hold the condensed requests' own message objects, so
    those must not be mutated in place after condensing.

    Supports ``mark()``/``restore()`` to unwind state when a surrounding
    database transaction rolls back.
    """

    def __init__(self) -> None:
        # walked-form content hash -> pool index
        self._hash_index: dict[str, int] = {}
        # retained previous-request lineages, with each message's pool index
        self._lineages: PrefixLineages[None, int] = PrefixLineages(
            _CALL_PREV_SLOTS, _CALL_PREV_MAX_IDLE
        )
        # undo log of hashes added (for mark/restore)
        self._added_hashes: list[str] = []

    @property
    def size(self) -> int:
        """Number of distinct pool entries indexed."""
        return len(self._hash_index)

    def match_prefix(self, msgs: Sequence[JsonValue]) -> PrefixMatch:
        """Pool indices for the longest shared prefix with a retained request.

        Args:
            msgs: New request's message list (pre-walk wire format).

        Returns:
            The matched prefix (``entries`` are its pool indices) and the
            lineage it came from. Hand it to the following ``set_prev`` for
            the same ``msgs``.
        """
        return self._lineages.match(None, msgs)

    def get_by_hash(self, hash_value: str) -> int | None:
        """Look up a pool index by walked-form content hash.

        Args:
            hash_value: Walked-form hash string.

        Returns:
            Pool index if found, ``None`` otherwise.
        """
        return self._hash_index.get(hash_value)

    def add_hash(self, hash_value: str, index: int) -> None:
        """Record a pool entry by its walked-form hash.

        Duplicate adds (same ``hash_value``) are silently ignored.

        Args:
            hash_value: Walked-form content hash.
            index: Pool index for this entry.
        """
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            self._added_hashes.append(hash_value)

    def set_prev(
        self,
        msgs: Sequence[JsonValue],
        indices: Sequence[int],
        match: PrefixMatch | None = None,
    ) -> None:
        """Record the request just condensed for prefix-matching later ones.

        Args:
            msgs: Pre-walk wire-format message list.
            indices: Corresponding pool indices, parallel to ``msgs``.
            match: The ``match_prefix`` result for these same ``msgs``, or
                ``None`` for callers that do not prefix-match.
        """
        self._lineages.record(
            match if match is not None else LineageMatch(None),
            list(msgs),
            list(indices),
        )

    def mark(self) -> int:
        """Return a mark for later ``restore()``.

        Returns:
            Opaque integer mark representing the current index state.
        """
        return len(self._added_hashes)

    def restore(self, mark: int) -> None:
        """Drop all pool references recorded since ``mark()`` was obtained.

        Hash entries are undone precisely (a stale entry would make the
        retry skip an insert and emit dangling refs). Lineages are
        accelerator-only, so all of them are dropped: any may hold indices
        of pool rows the rolled-back transaction created, and the next
        event's prefix scan then misses and falls through to hash dedup.

        Args:
            mark: Value previously returned by ``mark()``.
        """
        while len(self._added_hashes) > mark:
            del self._hash_index[self._added_hashes.pop()]
        self._lineages.clear()


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

        Identity-bucket entries are only registered for messages that are new
        to the pool (hash miss). A message whose content duplicates an
        already-pooled entry under a different id is re-walked and re-hashed
        on each event that re-sends it. This is a bounded cost (duplicate-
        content messages are rare), and avoids O(events × history) pinned
        objects for fresh-id scaffolds (bridge-style agents) where a hash hit
        would leave a useless bucket entry that could never produce a future
        identity hit.
    """
    update: dict[str, Any] = {}

    # Mirror condense_model_event_inputs guard ordering exactly:
    # passthrough if already condensed (refs set, input empty); skip if
    # input is empty (nothing to condense).
    if event.input_refs is not None and not event.input:
        pass
    elif event.input:
        raw_indices = messages.match_identity_run(event.input)
        run = len(raw_indices)
        for msg in event.input[run:]:
            index, identity = messages.lookup(msg)
            if index is None:
                walked = walk_message(msg)
                msg_hash = _pool._msg_hash(walked)
                index = messages.get_by_hash(msg_hash)
                if index is None:
                    index = add_message(msg_hash, walked)
                    identity = messages.add(msg, msg_hash, index)
            raw_indices.append(index)
            if identity and run == len(raw_indices) - 1:
                run += 1
        messages.set_identity_run(event.input, raw_indices, run)
        update["input"] = []
        update["input_refs"] = _compress_refs(raw_indices)

    call = event.call
    if call is not None and call.call_refs is None:
        msg_key = next((k for k in _CALL_MESSAGE_KEYS if k in call.request), None)
        msgs = call.request.get(msg_key) if msg_key else None
        if msgs and isinstance(msgs, list):
            match = calls.match_prefix(msgs)
            call_indices = match.entries
            for msg_value in msgs[match.length :]:
                walked_value = walk_call_message(msg_value)
                call_hash = _pool._call_hash(walked_value)
                call_index = calls.get_by_hash(call_hash)
                if call_index is None:
                    call_index = add_call(call_hash, walked_value)
                calls.add_hash(call_hash, call_index)
                call_indices.append(call_index)
            calls.set_prev(msgs, call_indices, match=match)
            new_request = {k: v for k, v in call.request.items() if k != msg_key}
            update["call"] = call.model_copy(
                update={
                    "request": new_request,
                    "call_refs": _compress_refs(call_indices),
                    "call_key": msg_key,
                }
            )

    return event.model_copy(update=update) if update else event
