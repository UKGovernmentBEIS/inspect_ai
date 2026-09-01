"""In-memory acceleration indices for message/call pool dedup.

These make per-event condensing cost proportional to the *new* messages
in each event rather than the full conversation history:

- ``MessagePoolIndex`` buckets on ``ChatMessage.id`` (a random UUID) and
  verifies candidates by object identity, then content equality. Agents
  reuse the same message objects across turns, so the identity fast path
  hits for the entire shared history without any serialization.
- ``CallPoolIndex`` exploits the append-mostly structure of provider wire
  requests: several recent request lineages are retained (up to
  ``_CALL_PREV_SLOTS``, evicted at random past that, and dropped once
  unmatched for ``_CALL_PREV_MAX_IDLE`` prefix scans) and each new request
  takes the best prefix match among them; only the divergent suffix is
  hashed. A request that fully consumes the lineage it matched replaces it;
  a partial match forks off as a sibling lineage, so concurrently
  interleaved streams keep prefix-hitting independently. The prefix scan is
  O(shared-history) comparisons per lineage with a small constant (no
  serialization or allocation); it is not O(new) like the message index,
  but in practice most events share a long stable prefix so the total work
  per event stays low.

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
distinct prior value exists. The call index has no such identity cache;
it instead deep-copies the wire values it retains for prefix matching
(``CallPoolIndex.set_prev``), so a caller mutating an already-condensed
wire request in place cannot make a later event's prefix match against a
value that was never pooled at that position.
"""

import copy
import dataclasses
import random
from collections.abc import Callable, Sequence
from typing import Any, Final, NamedTuple

from pydantic import BaseModel, JsonValue

from inspect_ai.model._chat_message import ChatMessage

from . import (
    _pool,  # accessed as module attributes so monkeypatching _pool._msg_hash is visible here
)
from ._model import ModelEvent
from ._pool import (
    _CALL_MESSAGE_KEYS,
    _compress_refs,
    _strict_eq,
    _strict_eq_prefix_len,
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

    def add(self, msg: ChatMessage, hash_value: str, index: int) -> None:
        """Record a pool entry.

        Messages with a content string over ``_BUCKET_CONTENT_LIMIT`` are
        recorded in the hash index only (see module docstring): bucketing
        would pin their payload in memory for the sample's lifetime.

        Args:
            msg: Pre-walk message object.
            hash_value: Walked-form content hash.
            index: Pool index for this entry.
        """
        bucket_key = msg.id if not _has_heavy_str(msg.__dict__) else None
        if bucket_key is not None:
            self._buckets.setdefault(bucket_key, []).append((msg, index))
        hash_added: str | None = None
        if hash_value not in self._hash_index:
            self._hash_index[hash_value] = index
            hash_added = hash_value
        if bucket_key is not None or hash_added is not None:
            self._log.append((bucket_key, hash_added))

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
"""Retained previous-request slots per CallPoolIndex.

Two slots per concurrent generate stream (one for the raw request lineage,
one for the transcript-condensed lineage the same stream also notifies), so
8 slots cover ~4 interleaved streams. Beyond capacity, degradation is
proportional under random eviction (see ``CallPoolIndex._evict_rng``) rather
than a cliff to zero, and is bounded above by the pre-cache full-walk cost.
Each slot pins one deep-copied request snapshot; for a raw lineage that can
be the sole owner of the full raw content across turns (strings shared with
live objects where they exist) — a deliberate memory tradeoff, bounded per
lineage.
"""


_CALL_PREV_MAX_IDLE: Final = 4 * _CALL_PREV_SLOTS
"""Prefix scans a lineage may go unmatched before it is dropped.

Retention is only a problem for *abandoned* lineages — a compaction cycle,
or a fork that never resumes. A live lineage is re-matched every turn, and
its content is kept alive by the condensed event anyway; an abandoned one
is pinned by nothing else and nothing else reclaims it.

The value is a heuristic, not a measured threshold. The floor it has to
clear is the interleave depth the slots exist for: ``_CALL_PREV_SLOTS``
lineages taken round-robin touch each one every 8 scans, so 4x that leaves
headroom for bursty interleaving before a live lineage is dropped. The
ceiling is what a wrong guess costs: a parked stream that resumes after its
slot aged out pays exactly one full re-hash of its history and then
re-establishes a lineage, which is the pre-index cost for that single call.
"""


# identity comparison: lineages are unique objects, never compared by value
@dataclasses.dataclass(eq=False)
class _PrevRequest:
    """One retained request lineage: pre-walk snapshots and their pool indices."""

    msgs: list[JsonValue]
    indices: list[int]
    last_used: int
    """Scan counter value when this lineage was last created or matched."""


class PrefixMatch(NamedTuple):
    """A ``match_prefix`` result, consumed by the following ``set_prev``."""

    indices: tuple[int, ...]
    """Pool indices of the matched prefix (empty if nothing matched)."""

    slot: _PrevRequest | None = None
    """Lineage the prefix came from, if any."""


class CallPoolIndex:
    """Prefix-diff lookup index for provider wire-request message lists.

    Wire-format call messages have no stable ids and no object reuse, so
    instead this index exploits the append-only growth pattern: retained
    lineages (see ``_CALL_PREV_SLOTS``) are compared element-by-element
    against new requests; the best-matching prefix is reused directly.

    A hash index covers the non-prefix tail so individual messages can still
    be deduplicated across events.

    Memory tradeoff (deliberate): each retained lineage pins one deep-copied
    request snapshot until replaced -- up to ``_CALL_PREV_SLOTS`` per sample,
    ``log_model_api`` only. A raw-form lineage can be the sole owner of its
    request's content strings across turns (the transcript condenses the live
    event's call after notifying). Fingerprinting instead would free them but
    re-serialize the prefix every event, reintroducing the O(N^2) hashing
    this index removed.

    A lineage nothing has matched in ``_CALL_PREV_MAX_IDLE`` prefix scans
    is dropped at the next append: only abandoned lineages (a compaction cycle,
    a fork that never resumes) hold content nothing else owns, and nothing
    else reclaims them. Dropping one costs at most a re-walk.

    Eviction beyond ``_CALL_PREV_SLOTS`` is random, not LRU: N interleaved
    streams accessed round-robin make LRU evict exactly the lineage each
    stream needs next, so at cap+1 lineages every lineage misses and
    re-hashes its whole history every turn. That cliff's size scales with
    conversation depth, so there is no single figure for it; random
    eviction keeps misses proportional to the excess instead. Guarded by
    ``test_buffer_condense_linear_across_slot_cap`` in
    ``tests/log/test_condense_linear.py``: its beyond-cap budget passes
    under this random eviction and fails if this index is made LRU.

    Supports ``mark()``/``restore()`` to unwind state when a surrounding
    database transaction rolls back.
    """

    def __init__(self) -> None:
        # walked-form content hash -> pool index
        self._hash_index: dict[str, int] = {}
        # retained previous-request lineages
        self._prevs: list[_PrevRequest] = []
        # monotonic count of prefix scans, for staleness eviction
        self._calls = 0
        # undo log of hashes added (for mark/restore)
        self._added_hashes: list[str] = []
        # Seeded for reproducibility; eviction choice affects performance
        # only, never output content.
        self._evict_rng = random.Random(0)

    @property
    def size(self) -> int:
        """Number of distinct pool entries indexed."""
        return len(self._hash_index)

    def match_prefix(self, msgs: Sequence[JsonValue]) -> PrefixMatch:
        """Pool indices for the longest shared prefix with a retained request.

        Compares against each retained lineage (see ``_CALL_PREV_SLOTS``) and
        returns the best match; comparison stops at the first differing
        element.

        Ties in match length break toward a lineage the request fully
        consumes, so a request repeating a strict prefix of a longer lineage
        replaces the slot it created last time instead of appending an
        identical sibling on every repeat.

        Args:
            msgs: New request's message list (pre-walk wire format).

        Returns:
            The matched prefix's pool indices and the lineage they came from
            (empty indices and no lineage if nothing matched). Hand the whole
            result to the following ``set_prev`` for the same ``msgs``.
        """
        self._calls += 1
        best = PrefixMatch(indices=())
        best_full = False
        # newest lineage first: a request usually extends the one it condensed
        # last, so the best match is normally the first candidate
        for prev in reversed(self._prevs):
            prefix_len = min(_strict_eq_prefix_len(msgs, prev.msgs), len(prev.indices))
            # the predicate mirrors set_prev's replacement test
            full = prefix_len == len(prev.msgs)
            # ties break toward a fully consumed lineage (see docstring); a
            # plain `>=` would prefer the *last* tie, which can be partial
            if (prefix_len, full) > (len(best.indices), best_full):
                best = PrefixMatch(indices=tuple(prev.indices[:prefix_len]), slot=prev)
                best_full = full
                # consuming both sides fully is the maximum of that ordering,
                # so no remaining lineage can win. Exiting on a full match of
                # `msgs` alone would take a partial match over a later exact
                # one and fork a duplicate slot.
                if full and prefix_len == len(msgs):
                    break
        # stamp the slot the scan SELECTED, not every slot it visited: the
        # early exit above means "visited" is not a usage signal
        if best.slot is not None:
            best.slot.last_used = self._calls
        return best

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

        Retains a deep copy of each message *value* (see class notes on
        in-place mutation). Given a ``match``, only the divergent tail is
        copied: the matched prefix's snapshots are carried over from the
        lineage that produced them — carrying from any other lineage would
        retain snapshots claiming pool indices for content never pooled at
        those positions. That lineage is replaced only when the match
        consumed it fully (the request extends it); a partial match keeps it
        and appends the new entry as a sibling lineage instead, since a
        partial match means the two lineages diverged from a shared prefix
        and replacing would merge them. With no match the entry is appended.
        Every call first drops any lineage unmatched for
        ``_CALL_PREV_MAX_IDLE`` prefix scans; an append still at cap after
        that evicts a random existing lineage (see class docstring: LRU is
        pathological here).

        Args:
            msgs: Pre-walk wire-format message list.
            indices: Corresponding pool indices, parallel to ``msgs``.
            match: The ``match_prefix`` result for these same ``msgs``. That
                pairing is a precondition: a match taken for a *different*
                message list carries snapshots that disagree with
                ``indices``. Omitting it (copy everything) is always safe
                for callers that do not prefix-match.
        """
        # Staleness eviction (see _CALL_PREV_MAX_IDLE), before the capacity
        # rules so it can make room instead of evicting at random, and before
        # the `match` is resolved so the drop guard below covers a `prev` this
        # aged out (a caller may interpose scans between the paired calls).
        self._prevs = [
            p for p in self._prevs if self._calls - p.last_used <= _CALL_PREV_MAX_IDLE
        ]
        prev = match.slot if match is not None else None
        prefix_len = len(match.indices) if match is not None else 0
        if prev is not None and prev not in self._prevs:
            # dropped since the match (restore(), or aged out above): nothing
            # valid to carry
            prev, prefix_len = None, 0
        carried = prev.msgs[:prefix_len] if prev is not None else []
        entry = _PrevRequest(
            msgs=carried + [copy.deepcopy(m) for m in msgs[prefix_len:]],
            indices=list(indices),
            last_used=self._calls,
        )
        # see docstring: replace only when the match fully consumed the
        # lineage, else keep it and append a sibling
        if prev is not None and prefix_len == len(prev.msgs):
            self._prevs.remove(prev)
        elif len(self._prevs) >= _CALL_PREV_SLOTS:
            # random, not LRU (see class docstring)
            del self._prevs[self._evict_rng.randrange(len(self._prevs))]
        self._prevs.append(entry)

    def mark(self) -> int:
        """Return a mark for later ``restore()``.

        Returns:
            Opaque integer mark representing the current index state.
        """
        return len(self._added_hashes)

    def restore(self, mark: int) -> None:
        """Drop all pool references recorded since ``mark()`` was obtained.

        Hash entries are undone precisely (a stale entry would make the
        retry skip an insert and emit dangling refs). The prefix-match
        state is accelerator-only, so it is dropped rather than rewound:
        the next event's prefix scan misses and falls through to hash
        dedup, which is always safe. Rewinding it would require holding
        snapshots of ``_prevs`` across the marked window, reintroducing
        aliasing to reason about for a path that only runs after a
        database transaction failure.

        Args:
            mark: Value previously returned by ``mark()``.
        """
        while len(self._added_hashes) > mark:
            del self._hash_index[self._added_hashes.pop()]
        # drop ALL lineages, not just the newest: any slot's indices may
        # reference pool rows the rolled-back transaction created (a match
        # taken before this point names a dropped lineage; set_prev ignores it)
        self._prevs = []


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
        raw_indices: list[int] = []
        for msg in event.input:
            index = messages.get(msg)
            if index is None:
                walked = walk_message(msg)
                msg_hash = _pool._msg_hash(walked)
                index = messages.get_by_hash(msg_hash)
                if index is None:
                    index = add_message(msg_hash, walked)
                    messages.add(msg, msg_hash, index)
            raw_indices.append(index)
        update["input"] = []
        update["input_refs"] = _compress_refs(raw_indices)

    call = event.call
    if call is not None and call.call_refs is None:
        msg_key = next((k for k in _CALL_MESSAGE_KEYS if k in call.request), None)
        msgs = call.request.get(msg_key) if msg_key else None
        if msgs and isinstance(msgs, list):
            match = calls.match_prefix(msgs)
            call_indices = list(match.indices)
            for msg_value in msgs[len(match.indices) :]:
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
