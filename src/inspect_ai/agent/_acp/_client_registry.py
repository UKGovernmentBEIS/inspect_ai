"""Generic single-driver-with-fallback client registry.

Shared by `_ApproverClientRegistry` and `_ElicitationClientRegistry` —
both manipulate attached clients as opaque references (lists, identity
comparisons, subscriber callbacks) without calling any
protocol-specific method, so the entire state machine is parametric on
the client protocol type `T`.

Why single-driver and not broadcast: ACP has no protocol-level cancel
for outbound requests, so broadcasting to N clients and racing leaves
the losers' editors showing a stale request card forever (whatever they
click later is silently discarded). Picking one driver keeps the UX
coherent: the operator sees the prompt on the client they're actually
using, others observe via the normal event stream.
"""

from __future__ import annotations

from logging import getLogger
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

logger = getLogger(__name__)


class _ClientDriverRegistry(Generic[T]):
    """Single-driver-with-fallback registry over a client protocol type.

    Clients move through three logical states:

    * **pending** — registered via :meth:`attach` but not yet promoted.
      Half-bound (replay in progress); invisible to :meth:`driver_chain`.
    * **ready** — promoted by :meth:`notify_attach` after the connection
      handler's bind is fully complete. Visible to dispatch.
    * **driver** — the most recently active ready client, set by
      :meth:`mark_active`. First entry in :meth:`driver_chain`.

    The split between pending and ready exists so the dispatch shim
    never routes a request into a half-bound client before its
    conversation context has been replayed to the operator.
    """

    def __init__(self) -> None:
        # Ready clients — the only ones :meth:`driver_chain` surfaces.
        self._clients: list[T] = []
        # Half-bound clients waiting for :meth:`notify_attach`.
        self._pending_clients: list[T] = []
        # The driver: most recently active client, set by
        # :meth:`mark_active`. ``None`` until any client is promoted, in
        # which case :meth:`driver_chain` falls back to first-attached.
        self._last_active: T | None = None
        # One-way flag: flips True on first attach (pending OR ready)
        # and never resets. Lets callers distinguish "no operator has
        # ever connected" from "operator was here, disconnected".
        self._ever_attached: bool = False
        # Fires on :meth:`notify_attach` (NOT on every :meth:`attach`).
        # The split exists so subscribers don't wake before the
        # connection is ready to receive a request AND has the
        # conversation context visible.
        self._attach_subscribers: list[Callable[[], None]] = []

    def attach(self, client: T) -> Callable[[], None]:
        """Register ``client`` as pending. Returns an idempotent unsubscribe.

        Attaching the same client object twice is not supported:
        :meth:`notify_attach` removes one pending entry per call, and
        :meth:`driver_chain`'s identity filter can't distinguish
        duplicate references. In practice each connection handler is
        its own client, so this doesn't occur.
        """
        self._pending_clients.append(client)
        self._ever_attached = True

        def _unsubscribe() -> None:
            # Client may be in either list depending on whether
            # `notify_attach` has fired yet. Best-effort removal from
            # both.
            try:
                self._pending_clients.remove(client)
            except ValueError:
                pass
            try:
                self._clients.remove(client)
            except ValueError:
                pass
            # If the active driver just detached, drop the slot so
            # `driver_chain` falls back cleanly to first-attached.
            if self._last_active is client:
                self._last_active = None

        return _unsubscribe

    def has_clients(self) -> bool:
        """True if at least one **ready** client is currently attached."""
        return bool(self._clients)

    def has_ever_attached(self) -> bool:
        """True if any client has ever attached (pending or ready)."""
        return self._ever_attached

    def subscribe_attach(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register ``callback`` to fire on every :meth:`notify_attach`.

        Returns an idempotent unsubscribe callable. Subscribers fire
        from :meth:`notify_attach`, i.e. AFTER replay completes and
        AFTER :meth:`mark_active` promotes the new client. Subscribers
        can safely re-query :meth:`driver_chain`.
        """
        self._attach_subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._attach_subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def notify_attach(self, client: T) -> None:
        """Promote ``client`` from pending to ready, then fire subscribers.

        Promotion is gated on the client currently being pending. If
        the client was unsubscribed between :meth:`attach` and
        :meth:`notify_attach`, we must NOT fabricate a ready entry with
        no unsubscribe left to remove it (would leak a stale client
        into :meth:`driver_chain` forever). Re-notify on an already-
        ready client is a no-op for state.

        Subscribers fire either way — a spurious wake-up is harmless
        because consumers re-snapshot the chain and re-park if
        nothing changed.
        """
        try:
            self._pending_clients.remove(client)
        except ValueError:
            # Client isn't pending. Either already promoted (re-notify)
            # or gone (unsub raced; don't fabricate a ready entry).
            pass
        else:
            # Removed from pending → real first-time promotion.
            if client not in self._clients:
                self._clients.append(client)
        for cb in list(self._attach_subscribers):
            try:
                cb()
            except Exception:
                logger.exception(
                    "_ClientDriverRegistry attach subscriber raised; continuing"
                )

    def mark_active(self, client: T) -> None:
        """Promote ``client`` to be the driver for subsequent requests.

        Accepts clients in EITHER ``_pending_clients`` or ``_clients``
        — bind-time promotion fires while the client is still pending
        (the :meth:`notify_attach` call right after moves it to ready).
        Silently no-ops if the client isn't in either list (race with
        detach).
        """
        if client in self._clients or client in self._pending_clients:
            self._last_active = client

    def driver_chain(self) -> list[T]:
        """Clients in fallback order: driver first, then others by attach order.

        Reads from READY clients only — pending (half-bound) clients
        are invisible. Returns a snapshot copy so iteration stays
        stable against concurrent attach / detach.
        """
        if not self._clients:
            return []
        driver = self._last_active
        if driver is None or driver not in self._clients:
            # No driver yet (or marked driver is still pending) →
            # first-attached is the fallback driver.
            return list(self._clients)
        return [driver] + [c for c in self._clients if c is not driver]

    def clear(self) -> None:
        self._clients.clear()
        self._pending_clients.clear()
        self._last_active = None
        self._attach_subscribers.clear()
