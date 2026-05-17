"""Exception-handling helpers for the ACP server.

The ACP server runs in the same process as the eval scaffold. Two
patterns recur often enough across the package that they live as
shared context managers:

1. :func:`acp_guard` — **"log a warning and suppress"**. Used in
   :class:`LiveAcpSession` methods, the approval shim, and any other
   site that wants "if this fails, log and degrade quietly." Two
   calling shapes:

   - Implicit fall-through (most common): put the degraded default
     on the line after the ``with``. The return / fallthrough fires
     only when the body raised (the CM suppressed).
   - Explicit status check: bind the status with ``as g`` and check
     ``g.failed`` to branch (typically ``continue`` inside a loop).

2. :func:`acp_send_guard` — **"send and exit if peer dropped"**.
   Used at every ``send_notification`` / ``send_request`` site in
   the forwarders. Distinguishes normal-disconnect exceptions (logged
   at ``DEBUG``; routine when a client closes — every subsequent
   send would fail the same way) from unexpected exceptions (logged
   at ``WARNING``). Caller checks ``s.should_exit`` and breaks /
   returns.

In both cases ``CancelledError`` / ``trio.Cancelled`` propagate
naturally because they inherit from ``BaseException`` (not
``Exception``), so structured concurrency keeps working.

Both CMs are sync; the body inside the ``with`` may ``await`` freely.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from logging import getLogger
from typing import Iterator

import anyio

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Normal-disconnect exception set
# ---------------------------------------------------------------------------

# Exception types we treat as "the peer closed normally" rather than
# unexpected errors. Without this split, every remaining notification
# in a forwarder's send pipeline at disconnect time would emit a
# WARNING with a stack trace — noisy on local IPC, much noisier when
# ``--acp-server`` is bound to a routable interface (``host:port``
# form) where Wi-Fi / NAT timeouts can drop connections regularly.
NORMAL_DISCONNECT_EXC: tuple[type[BaseException], ...] = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
    EOFError,
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
)


# ---------------------------------------------------------------------------
# acp_guard — log + suppress
# ---------------------------------------------------------------------------


@dataclass
class GuardStatus:
    """Status returned by :func:`acp_guard`.

    ``failed`` is True iff the body raised a non-cancellation
    exception (the CM logged it and suppressed). Callers can ignore
    the status entirely when the degraded default is a single
    statement on the line after the ``with`` — implicit fall-through
    handles that case.
    """

    failed: bool = False


@contextlib.contextmanager
def acp_guard(message: str) -> Iterator[GuardStatus]:
    """Catch non-cancellation exceptions, log at WARNING, suppress.

    Usage — implicit fall-through (most common)::

        def has_approver_clients(self) -> bool:
            with acp_guard("ACP has_approver_clients raised; ..."):
                return self._approvers.has_clients()
            return False  # degraded default; only reached on failure

    Usage — explicit status (when you need to branch inside a loop)::

        for event in events:
            with acp_guard("ACP serialize failed; skipping") as g:
                payload = event.model_dump(...)
            if g.failed:
                continue
            ...

    ``CancelledError`` is a ``BaseException`` subclass, so the
    ``except Exception:`` inside this CM does NOT catch it. Sample-
    level cancel and structured-concurrency cancel still propagate.
    """
    status = GuardStatus()
    try:
        yield status
    except Exception:
        logger.warning(message, exc_info=True)
        status.failed = True


# ---------------------------------------------------------------------------
# acp_send_guard — disconnect-aware send guard
# ---------------------------------------------------------------------------


@dataclass
class SendStatus:
    """Status returned by :func:`acp_send_guard`.

    ``disconnected`` — the peer closed normally; caller should exit
    its loop quietly.
    ``failed`` — an unexpected exception was caught; caller should
    exit its loop (the connection is probably toast).
    ``should_exit`` — true on either disconnect or unexpected.
    """

    disconnected: bool = False
    failed: bool = False

    @property
    def should_exit(self) -> bool:
        return self.disconnected or self.failed


@contextlib.contextmanager
def acp_send_guard(message: str) -> Iterator[SendStatus]:
    """Guard a forwarder send site; distinguish disconnect from error.

    Usage::

        for notif in stream:
            ...
            with acp_send_guard("ACP semantic forwarder send") as s:
                await self._send_session_update(out)
            if s.should_exit:
                return

    - Normal-disconnect exception → log at ``DEBUG`` (one line, no
      stack trace; routine when a client closes), set
      ``status.disconnected``.
    - Any other exception → log at ``WARNING`` with ``exc_info=True``,
      set ``status.failed``.
    - Success → status flags stay False; caller continues.

    Caller MUST check ``status.should_exit`` after the ``with`` block
    and break / return on True — there is no way for a CM to force
    control flow on the enclosing scope.

    ``CancelledError`` propagates naturally (BaseException, not
    Exception).
    """
    status = SendStatus()
    try:
        yield status
    except NORMAL_DISCONNECT_EXC as exc:
        logger.debug("%s: peer disconnected (%s)", message, type(exc).__name__)
        status.disconnected = True
    except Exception:
        logger.warning(message, exc_info=True)
        status.failed = True
