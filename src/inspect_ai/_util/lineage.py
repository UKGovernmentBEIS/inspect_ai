"""Prefix lineages: matching append-mostly message lists against recent ones.

Model requests grow by appending to the previous request, so the messages a
request shares with an earlier one are a leading run. ``PrefixLineages``
retains a few recent message lists (lineages) and finds the one sharing the
longest leading run with a new list; callers reuse what they derived for
that run and process only the remainder.

Comparison is ``eq_prefix_len``: one C-level list ``==`` over the shared
span (identical objects short-circuit), with the type-strict check of
``strict_eq`` only for elements that need it. Retained lists hold the
callers' own objects rather than copies, so callers must treat the lists
they hand in as read-only.
"""

import builtins
import dataclasses
import random
import sys
from collections.abc import Callable, Hashable, Iterator, Sequence
from itertools import compress
from typing import Generic, TypeVar

from pydantic import BaseModel

if sys.version_info >= (3, 15):
    _MISSING = builtins.sentinel("_MISSING")
else:
    _MISSING = object()


def strict_eq(a: object, b: object) -> bool:
    """Equality that distinguishes values with different JSON serializations.

    Python ``==`` conflates values that serialize differently: ``0 == 0.0``
    and ``True == 1``, but ``json.dumps`` emits different bytes for each, so
    content hashes differ. An ``==``-based merge of such values would reuse
    an entry whose stored bytes round-trip to the *other* value — silent
    data corruption. This comparison requires matching types for scalars
    (recursing into models, dataclasses, dicts, and lists), so a merge
    implies identical serialization.
    """
    if a is b:
        return True
    ta, tb = type(a), type(b)
    if ta is not tb:
        return False
    if isinstance(a, BaseModel):
        return strict_eq(a.__dict__, b.__dict__)  # type: ignore[attr-defined]
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        return strict_eq(vars(a), vars(b))
    if type(a) is dict and type(b) is dict:
        if len(a) != len(b):
            return False
        for k, v in a.items():
            other = b.get(k, _MISSING)
            if other is _MISSING or not strict_eq(v, other):
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
    if (type(a) is list and type(b) is list) or (type(a) is tuple and type(b) is tuple):
        return len(a) == len(b) and all(strict_eq(x, y) for x, y in zip(a, b))
    return a == b


def needs_strict_eq(value: object) -> bool:
    """Whether ``==`` on ``value`` could pass where ``strict_eq`` fails.

    ``==`` against a value built only from ``str``, ``None``, ``list``, and
    ``dict`` with ``str`` keys implies ``strict_eq``: each of those leaves
    compares equal only to a leaf with the same JSON serialization. Numbers,
    bools, tuples, models, dataclasses, and non-``str`` keys can compare
    equal across types, so values containing them need the strict check.
    """
    stack = [value]
    while stack:
        v = stack.pop()
        if type(v) is str or v is None:
            continue
        if type(v) is dict:
            if not all(type(k) is str for k in v):
                return True
            stack.extend(v.values())
        elif type(v) is list:
            stack.extend(v)
        else:
            return True
    return False


def eq_prefix_len(
    a: Sequence[object], b: Sequence[object], b_strict: Sequence[bool]
) -> int:
    """Number of leading elements of ``a`` and ``b`` that are ``strict_eq``.

    ``b_strict`` holds ``needs_strict_eq`` of each ``b`` element. The shared
    span is compared as list slices (C-level, identity short-circuit per
    element), bisecting to the first difference; only flagged elements that
    are not the very same object get ``strict_eq``.
    """
    a = a if type(a) is list else list(a)
    b = b if type(b) is list else list(b)
    n = min(len(a), len(b))
    k = n
    if a[:n] != b[:n]:
        lo, hi = 0, n
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if a[lo:mid] == b[lo:mid]:
                lo = mid
            else:
                hi = mid
        k = lo
    for i in compress(range(k), b_strict):
        if a[i] is not b[i] and not strict_eq(a[i], b[i]):
            return i
    return k


K = TypeVar("K", bound=Hashable)
E = TypeVar("E")


# identity comparison: lineages are unique objects, never compared by value
@dataclasses.dataclass(eq=False)
class Lineage(Generic[K, E]):
    """One retained message list and what a caller derived for each message."""

    key: K
    """Lineages only match requests with an equal key."""

    snapshots: list[object]
    """What later lists are compared against, one per message."""

    strict: list[bool]
    """``needs_strict_eq`` of each snapshot."""

    entries: list[E]
    """Caller-derived value for each message, parallel to ``snapshots``."""

    last_used: int
    """Scan counter value when this lineage was last created or matched."""

    def __len__(self) -> int:
        return len(self.snapshots)


@dataclasses.dataclass(frozen=True)
class LineageMatch(Generic[K, E]):
    """A ``PrefixLineages.match`` result, consumed by the following ``record``."""

    key: K
    """Key the list was matched with."""

    lineage: Lineage[K, E] | None = None
    """Lineage the shared run came from, if any."""

    length: int = 0
    """Number of leading messages shared with ``lineage``."""

    @property
    def snapshots(self) -> list[object]:
        """New list of the matched lineage's snapshots for the shared run."""
        return self.lineage.snapshots[: self.length] if self.lineage else []

    @property
    def entries(self) -> list[E]:
        """New list of the matched lineage's entries for the shared run."""
        return self.lineage.entries[: self.length] if self.lineage else []


PrefixLen = Callable[[Sequence[object], Lineage[K, E]], int]
"""Leading messages of a list shared with a lineage's snapshots."""


def snapshot_prefix_len(msgs: Sequence[object], lineage: Lineage[K, E]) -> int:
    """``eq_prefix_len`` against a lineage's snapshots."""
    return eq_prefix_len(msgs, lineage.snapshots, lineage.strict)


class PrefixLineages(Generic[K, E]):
    """Recent message lists, matched by longest shared leading run.

    Up to ``slots`` lineages are retained. A list replaces the lineage it
    matched only when it consumes that lineage fully — it extends it. A
    partial match is a sibling forked from a shared prefix (fork()/collect()
    streams share pre-fork history); replacing would merge the two, and they
    would then alternately destroy each other's tails. An unmatched list is
    appended.

    Ties in match length break toward a fully consumed lineage, so a list
    repeating a strict prefix of a longer lineage replaces the lineage it
    created last time instead of appending an identical sibling each time.

    Eviction beyond ``slots`` is random, not LRU: N interleaved streams
    accessed round-robin make LRU evict exactly the lineage each stream
    needs next, so at cap+1 every stream misses on every call. Random
    eviction keeps misses proportional to the excess. A lineage unmatched
    for ``max_idle`` scans is dropped at the next ``record``: only abandoned
    lineages (a compaction cycle, a fork that never resumes) hold objects
    nothing else references.
    """

    def __init__(
        self,
        slots: int,
        max_idle: int,
        prefix_len: PrefixLen[K, E] = snapshot_prefix_len,
    ) -> None:
        self._slots = slots
        self._max_idle = max_idle
        self._prefix_len = prefix_len
        self._lineages: list[Lineage[K, E]] = []
        # monotonic count of scans, for staleness eviction
        self._scans = 0
        # seeded: eviction choice affects performance only, never output
        self._evict_rng = random.Random(0)

    def __len__(self) -> int:
        return len(self._lineages)

    def __iter__(self) -> Iterator[Lineage[K, E]]:
        """Retained lineages, oldest first."""
        return iter(self._lineages)

    def match(self, key: K, msgs: Sequence[object]) -> LineageMatch[K, E]:
        """The retained lineage sharing the longest leading run with ``msgs``.

        Args:
            key: Only lineages recorded with an equal key are considered.
            msgs: The new message list.

        Returns:
            The best match (no lineage and length 0 if nothing matched).
            Hand it to the following ``record`` for the same ``msgs``.
        """
        self._scans += 1
        best: Lineage[K, E] | None = None
        best_len = 0
        best_full = False
        # newest first: a list usually extends the most recent lineage
        for lineage in reversed(self._lineages):
            if lineage.key != key:
                continue
            size = len(lineage)
            bound = min(len(msgs), size)
            if (bound, bound == size) <= (best_len, best_full):
                continue
            n = self._prefix_len(msgs, lineage)
            full = n == size
            if (n, full) > (best_len, best_full):
                best, best_len, best_full = lineage, n, full
                # consuming both sides fully is the maximum of that ordering
                if full and n == len(msgs):
                    break
        # stamp the lineage the scan selected, not every one it visited
        if best is not None:
            best.last_used = self._scans
        return LineageMatch(key, best, best_len)

    def record(
        self,
        match: LineageMatch[K, E],
        snapshots: list[object],
        entries: list[E],
    ) -> None:
        """Retain a message list for matching later ones.

        Args:
            match: The ``match`` result for this list; its key is the
                lineage's, and its lineage's strict flags are reused for the
                shared run.
            snapshots: What later lists compare against, one per message.
            entries: Caller-derived value for each message.
        """
        carried = match.lineage.strict[: match.length] if match.lineage else []
        strict = carried + [needs_strict_eq(s) for s in snapshots[len(carried) :]]
        self._lineages = [
            lineage
            for lineage in self._lineages
            if self._scans - lineage.last_used <= self._max_idle
        ]
        prev = match.lineage if match.lineage in self._lineages else None
        if prev is not None and match.length == len(prev):
            self._lineages.remove(prev)
        elif len(self._lineages) >= self._slots:
            del self._lineages[self._evict_rng.randrange(len(self._lineages))]
        self._lineages.append(
            Lineage(
                key=match.key,
                snapshots=snapshots,
                strict=strict,
                entries=entries,
                last_used=self._scans,
            )
        )

    def clear(self) -> None:
        """Drop every lineage."""
        self._lineages.clear()
