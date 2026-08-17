"""Short-TTL cache of resolved terminal per-sample sources.

Once a sample attempt is terminal, its transcript and conversation are
immutable — yet the per-sample control reads re-resolve their terminal source
on every request: ``GET /evals/<id>/sample/events`` re-reads, re-parses, and
re-validates the entire flushed sample per *page* (O(N²/limit) aggregate work
for a client paginating an N-event transcript, and one full-transcript parse
per poll for a follower that never sees a new event), and
``.../sample/messages`` re-pays the whole-conversation parse plus attachment
resolution per poll. All of it runs synchronously on the eval's own event
loop. Caching the *resolved source* for a few seconds collapses both
amplifications without touching the resolution logic itself.

Staleness is bounded by construction:

- An entry expires ``ttl`` seconds after *insertion*; a hit never refreshes
  the clock. So even a steady poller (whose hits would otherwise keep an
  entry alive forever) re-resolves at least once per TTL, and a served
  source is never more than ``ttl`` seconds old.
- The one way a terminal source is superseded is a retry — a fresh attempt
  under the same ``(eval_id, sample_id, epoch)``. The events / messages
  readers call :func:`invalidate_terminal_sources` whenever they resolve a
  *running* source for the key, dropping it from *every* registered cache —
  so a poll on either endpoint that observes the retry in flight drops the
  prior attempt's entry immediately rather than waiting out the TTL, for
  both endpoints (not just the one that observed it). (A retry that starts
  *and* terminates between polls can still serve the prior attempt for up
  to one TTL; the attempt nonce in the events cursor means a client's
  cursor simply restarts rather than misreading offsets.)
- :func:`clear_terminal_source_caches` drops everything when the eval-state
  registry is cleared (``clear_all_eval_states``) — every cached source was
  derived from a registered eval, so none can outlive the registry.

No lock: inspect runs on a single event-loop thread (control-server handlers
included) and every dict mutation (get / put / invalidate / clear) runs with
no await point, so there is no cross-thread or interleaved access to protect.
The one await in :meth:`TerminalSourceCache.get_or_resolve` sits between a
get and a put — see its docstring for why the interleaving it admits is
harmless.
"""

from __future__ import annotations

import time
import weakref
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")

SourceKey = tuple[str, str, int]
"""Cache key: the request identity ``(eval_id, sample_id, epoch)``.

``sample_id`` is the raw request string (not the reconciled stored id) —
resolution reconciles digit-looking ids deterministically, so equal request
strings always resolve to the same sample."""

TERMINAL_SOURCE_TTL = 5.0
"""Seconds a resolved terminal source is served before re-resolution.

Small enough that the retry-staleness window (see the module docstring) is
negligible next to a sample re-run, large enough that pagination and polling
pay one resolution per TTL instead of one per request."""

TERMINAL_SOURCE_MAX_ENTRIES = 8
"""Entry cap, evicting oldest-inserted first.

An events entry holds a sample's full parsed event list, so the cap bounds
memory at "a handful of samples being watched at once" — the actual shape of
control-channel traffic — rather than one entry per sample ever read."""

# Every live cache (the events / messages module singletons), so the teardown
# boundary can clear them without importing their host modules. Weak so that
# transient instances (e.g. test-constructed replacements) don't accumulate
# for the life of the process.
_caches: "weakref.WeakSet[TerminalSourceCache[Any]]" = weakref.WeakSet()


class TerminalSourceCache(Generic[T]):
    """A tiny insertion-time-TTL cache for resolved terminal sources.

    See the module docstring for the rationale and staleness bounds. The
    ``clock`` parameter exists for tests; production instances use
    ``time.monotonic``.
    """

    def __init__(
        self,
        ttl: float = TERMINAL_SOURCE_TTL,
        max_entries: int = TERMINAL_SOURCE_MAX_ENTRIES,
        clock: "Callable[[], float]" = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        # key -> (inserted_at, value); dict insertion order is eviction order
        self._entries: dict[SourceKey, tuple[float, T]] = {}
        _caches.add(self)

    def get(self, key: SourceKey) -> T | None:
        """The cached source for ``key``, or ``None`` if absent or expired.

        Expiry is measured from insertion — a hit does not extend an entry's
        life (see the module docstring for why).
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        inserted_at, value = entry
        if self._clock() - inserted_at >= self._ttl:
            del self._entries[key]
            return None
        return value

    def put(self, key: SourceKey, value: T) -> None:
        """Cache ``value`` under ``key``, pruning expired and over-cap entries."""
        now = self._clock()
        for expired in [
            k for k, (at, _) in self._entries.items() if now - at >= self._ttl
        ]:
            del self._entries[expired]
        # re-insert (rather than overwrite) so insertion order tracks recency
        self._entries.pop(key, None)
        while len(self._entries) >= self._max_entries:
            del self._entries[next(iter(self._entries))]
        self._entries[key] = (now, value)

    async def get_or_resolve(
        self,
        key: SourceKey,
        resolve: "Callable[[], Awaitable[T | None]]",
    ) -> T | None:
        """The source for ``key``: cached if present, else via ``resolve``.

        A ``None`` resolution is never cached — a just-flushed sample must
        become visible on the next request, not a TTL later.

        The await on ``resolve`` sits between the get and the put, so an
        :meth:`invalidate` landing mid-resolution can be overwritten by the
        put. That interleaving is harmless: any later request that observes
        the superseding attempt invalidates again, and the entry is in any
        case bounded by the insertion-time TTL.
        """
        value = self.get(key)
        if value is None:
            value = await resolve()
            if value is not None:
                self.put(key, value)
        return value

    def invalidate(self, key: SourceKey) -> None:
        """Drop ``key`` — a running (retry) attempt supersedes its entry."""
        self._entries.pop(key, None)

    def clear(self) -> None:
        """Drop every entry."""
        self._entries.clear()


def invalidate_terminal_sources(key: SourceKey) -> None:
    """Drop ``key`` from every terminal-source cache.

    Called by the events / messages readers when they resolve a *running*
    source for the key: the retry supersedes the prior attempt's terminal
    source in every projection of it, so the invalidation must reach both
    caches — a per-cache invalidate would leave the other endpoint serving
    the prior attempt for up to one TTL after the retry was observed.
    """
    for cache in _caches:
        cache.invalidate(key)


def clear_terminal_source_caches() -> None:
    """Drop every terminal-source cache's entries.

    Called from ``clear_all_eval_states`` (the eval-state teardown boundary):
    cached sources are derived from registered evals, so they must not
    outlive the registry.
    """
    for cache in _caches:
        cache.clear()
