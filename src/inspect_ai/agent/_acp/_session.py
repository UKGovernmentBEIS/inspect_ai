"""Agent Client Protocol session foundation.

Phase 1 of the Agent ACP feature: types, factory, and accessors only. No
agent integration, no cancellation mechanics, no schema changes — those
land in later phases (see ``design/agent-acp.md``).

An ``AcpSession`` is the per-agent ACP facade. There are two
implementations:

- ``_NoOpAcpSession`` — null object used as the default ContextVar value
  and as the shadow when ``acp_session()`` is opened inside an already
  active session (sub-agent case).
- ``_LiveAcpSession`` — the active implementation that owns the
  in-process pub/sub bus.

Future phases hang user-message queueing, turn cancel scopes, and
``session/update`` event publishing on this foundation.
"""

import contextlib
from contextvars import ContextVar
from logging import getLogger
from types import TracebackType
from typing import Any, AsyncIterator, Protocol, runtime_checkable

import anyio
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
)
from shortuuid import uuid

logger = getLogger(__name__)

# Phase 1 placeholder; Phase 6 will tighten this to a session/update union.
AcpUpdate = dict[str, Any]

# Bounded subscriber buffer. A slow subscriber drops updates rather than
# stalling the agent; replay-on-attach (Phase 10) handles lossless catch-up
# for clients that need it.
_SUBSCRIBER_BUFFER_SIZE = 256

# Sentinel session_id for the no-op variant so callers never need
# isinstance guards.
_NOOP_SESSION_ID = "noop"


@runtime_checkable
class AcpSession(Protocol):
    """Per-agent ACP session facade.

    Phase 1 surface only: an async context manager plus an in-process
    pub/sub interface for ``session/update``-shaped payloads. Cancel,
    turn, and user-message-queue methods are added in Phase 3.
    """

    @property
    def session_id(self) -> str:
        """Opaque identifier for this session.

        Stable for the lifetime of a live session; returns the sentinel
        ``"noop"`` for the no-op variant so callers never need
        ``isinstance`` guards before logging or correlating.
        """
        ...

    async def __aenter__(self) -> "AcpSession":
        """Enter the session scope.

        Returns ``self``. The session is installed in the ACP
        ContextVar by the ``acp_session()`` factory immediately before
        this is called; consumers can call :func:`current_acp_session`
        from anywhere inside the scope to retrieve it.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the session scope.

        Closes every attached subscriber's send half so receivers see
        clean EOF. No drain — closing *is* the termination signal.
        """
        ...

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Register a subscriber and return its receive stream.

        Caller iterates with ``async for update in stream``. The session
        closes all subscriber streams on exit, so an idle ``async for``
        terminates cleanly.
        """
        ...

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """Unregister a subscriber previously returned by :meth:`attach`.

        Closes the matching send half and drops the subscriber from the
        fan-out list. Safe to call with an already-detached or unknown
        stream — silently does nothing.
        """
        ...

    def publish(self, update: AcpUpdate) -> None:
        """Fan ``update`` out to every attached subscriber.

        Non-blocking: a subscriber with a full buffer drops the update
        with a logged warning rather than stalling the producer.
        """
        ...


class _NoOpAcpSession:
    """No-op session installed when ACP is not active or shadowed.

    ``attach()`` returns an already-closed receive stream so callers can
    still write transport code uniformly — the ``async for`` just exits
    immediately.
    """

    @property
    def session_id(self) -> str:
        """Always returns the ``"noop"`` sentinel."""
        return _NOOP_SESSION_ID

    async def __aenter__(self) -> "AcpSession":
        """No-op enter; returns ``self``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """No-op exit."""
        return None

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Return an already-closed receive stream.

        Lets callers wire transport code identically against either
        variant — iterating the stream yields no updates and exits
        immediately.
        """
        send, receive = anyio.create_memory_object_stream[AcpUpdate](0)
        send.close()
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """No-op detach."""
        return None

    def publish(self, update: AcpUpdate) -> None:
        """No-op publish — updates are discarded."""
        return None


class _LiveAcpSession:
    """Active ACP session: owns the in-process pub/sub bus.

    Installed by :func:`acp_session` as the outermost ACP scope in a
    sample. Subscribers (the in-process TUI in Phase 7, the socket
    transport in Phase 8+) call :meth:`attach` to receive
    ``session/update``-shaped payloads.
    """

    def __init__(self) -> None:
        self._session_id: str = uuid()
        self._subscribers: list[
            tuple[
                MemoryObjectSendStream[AcpUpdate],
                MemoryObjectReceiveStream[AcpUpdate],
            ]
        ] = []

    @property
    def session_id(self) -> str:
        """Opaque, stable identifier minted at construction (shortuuid)."""
        return self._session_id

    async def __aenter__(self) -> "AcpSession":
        """Enter the session scope; returns ``self``."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close every attached subscriber's send half and clear the list.

        Receivers see clean EOF (``anyio.EndOfStream``) and their
        ``async for`` loops terminate.
        """
        for send, _ in self._subscribers:
            send.close()
        self._subscribers.clear()

    def attach(self) -> MemoryObjectReceiveStream[AcpUpdate]:
        """Create a new subscriber stream pair, keep the send half, return the receive half.

        Each subscriber gets its own bounded buffer; slow consumers
        don't stall siblings.
        """
        send, receive = anyio.create_memory_object_stream[AcpUpdate](
            max_buffer_size=_SUBSCRIBER_BUFFER_SIZE
        )
        self._subscribers.append((send, receive))
        return receive

    def detach(self, stream: MemoryObjectReceiveStream[AcpUpdate]) -> None:
        """Close the matching send half and drop the subscriber.

        Identity match (``receive is stream``). Safe to call with an
        unknown or already-detached stream — silently does nothing.
        """
        for i, (send, receive) in enumerate(self._subscribers):
            if receive is stream:
                send.close()
                del self._subscribers[i]
                return

    def publish(self, update: AcpUpdate) -> None:
        """Fan ``update`` out non-blockingly to all attached subscribers.

        A subscriber with a full buffer logs a warning and drops the
        update. A subscriber whose receive half was closed by the
        consumer is pruned from the subscriber list so subsequent
        publishes don't keep hitting the same dead stream.
        """
        dead: list[int] = []
        for i, (send, _) in enumerate(self._subscribers):
            try:
                send.send_nowait(update)
            except anyio.WouldBlock:
                logger.warning(
                    f"AcpSession {self._session_id}: subscriber buffer full; "
                    "dropping update"
                )
            except anyio.BrokenResourceError:
                # Receive end closed by the consumer; prune.
                dead.append(i)
        for i in reversed(dead):
            send, _ = self._subscribers.pop(i)
            send.close()


def _is_noop(session: AcpSession) -> bool:
    return isinstance(session, _NoOpAcpSession)


_NOOP_SINGLETON: AcpSession = _NoOpAcpSession()

_acp_var: ContextVar[AcpSession] = ContextVar("_acp_session", default=_NOOP_SINGLETON)


@contextlib.asynccontextmanager
async def acp_session() -> AsyncIterator[AcpSession]:
    """Open an ACP session for the enclosing scope.

    If an ACP session is already active in this context (e.g. we are
    inside a sub-agent invoked from a top-level agent that already
    opened one), this scope installs a no-op shadow so nested agents
    never accidentally drive the outer session. The first non-shadowed
    entry installs the real session.

    Usage::

        async with acp_session() as acp:
            ...
    """
    current = _acp_var.get()
    install: AcpSession = (
        _NoOpAcpSession() if not _is_noop(current) else _LiveAcpSession()
    )
    token = _acp_var.set(install)
    try:
        async with install:
            yield install
    finally:
        _acp_var.reset(token)


def current_acp_session() -> AcpSession:
    """Return the currently active ACP session without entering a scope.

    Returns the no-op singleton when no ACP session is active. Safe to
    call from anywhere; never blocks; never raises.
    """
    return _acp_var.get()
