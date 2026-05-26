"""ACP routing for `ask_user` elicitation prompts.

When ``--acp-server`` is active (an :class:`AcpServer` is accepting
external clients), ``request_input`` routes the prompt through ACP's
``elicitation/create`` rather than opening the in-proc Textual panel
or console handler. When ``--acp-server`` is NOT active this module's
entry point returns ``None`` and the caller
(:func:`inspect_ai.input.builtin._dispatch_builtin`) falls through to
the existing panel / console flow.

Exclusive routing: under ``--acp-server`` the shim *parks* (does not
fall through) when no ACP client is attached yet, waiting for one to
arrive. See ``design/acp/elicitation.md`` "Routing policy" for the
rationale (no notification-driven race against the in-proc panel).

Mirrors the approval shim at
:mod:`inspect_ai.approval._human.acp` one-for-one: same
single-driver-with-fallback semantics, same drain barrier, same
park-on-attach semantics, same hard contract (never propagate a
non-cancellation exception). Driver chain + capability gating live in
:class:`~inspect_ai.agent._acp.transport.AcpTransport`; this module
just consumes them.

asyncio boundary note
=====================

Like the approval shim, this module is **asyncio-bound** at the
``send_request`` boundary because the ``acp`` library is
asyncio-only. Cancellation catches use
``anyio.get_cancelled_exc_class()`` so they're backend-agnostic.
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Callable, Protocol

import anyio
from acp.schema import (
    AcceptElicitationResponse,
    CancelElicitationResponse,
    DeclineElicitationResponse,
)

from inspect_ai.agent._acp._guards import acp_guard
from inspect_ai.agent._acp.server import acp_server_accepting_clients
from inspect_ai.agent._acp.transport import ElicitationRequest

from ._types import InputRequest, InputResult

if TYPE_CHECKING:
    from inspect_ai.agent._acp.transport import ElicitationClient

logger = getLogger(__name__)


class _ElicitationRoutingSession(Protocol):
    """Narrowed view of ``AcpTransport`` for the elicitation shim.

    Only the primitives the shim actually uses. Narrowed (rather than
    parameterising on the full transport) so tests can pass a minimal
    stub without implementing the full session surface — same pattern
    as :class:`_ApprovalRoutingSession` in
    :mod:`inspect_ai.approval._human.acp`.
    """

    @property
    def session_id(self) -> str: ...

    def elicitation_driver_chain(self) -> list["ElicitationClient"]: ...

    def subscribe_elicitation_attach(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]: ...


def _result_from_response(
    response: "AcceptElicitationResponse | DeclineElicitationResponse | CancelElicitationResponse",
) -> InputResult:
    """Map an ACP elicitation response to an :class:`InputResult`.

    ``accept`` → ``accepted`` with ``content`` carrying the form
    payload. ``decline`` → ``declined`` with no content (the user
    explicitly chose not to answer). ``cancel`` → ``cancelled``
    (the user backed out without a decision).
    """
    if isinstance(response, AcceptElicitationResponse):
        return InputResult(outcome="accepted", content=response.content)
    if isinstance(response, DeclineElicitationResponse):
        return InputResult(outcome="declined", content=None)
    if isinstance(response, CancelElicitationResponse):
        return InputResult(outcome="cancelled", content=None)
    # Defensive — _parse_elicitation_response upstream already guards
    # against unknown actions, but the response type is a union, so a
    # future ACP variant landing here would otherwise be silently
    # mis-mapped. Returning cancelled is the least-bad outcome for the
    # tool caller.
    logger.warning(
        "Unexpected ACP elicitation response type %s; treating as cancelled",
        type(response).__name__,
    )
    return InputResult(outcome="cancelled", content=None)


async def _request_from_driver_with_fallback(
    session: _ElicitationRoutingSession,
    request: ElicitationRequest,
) -> InputResult:
    """Send ``request`` to the driver; park-and-retry on chain exhaustion.

    Mirrors :func:`inspect_ai.approval._human.acp._request_from_driver_with_fallback`
    one-for-one — same routing model, same per-iteration sequence,
    same parking semantics. The only per-client difference: this
    calls :meth:`ElicitationClient.request_elicitation` instead of
    :meth:`ApproverClient.request_permission`.

    Exclusive-routing semantics: when no client is attached (including
    the "no client has ever attached" case on the very first
    interaction), this parks on
    :meth:`AcpTransport.subscribe_elicitation_attach` until one
    arrives. ``--acp-server`` committed the eval to ACP as the human
    channel; falling through to the in-proc panel / console would
    break the notification-driven workflow (see
    ``design/acp/elicitation.md`` "Routing policy"). Cancellation
    unwinds the park cleanly via ``anyio.Event.wait``.
    """
    cancel_exc = anyio.get_cancelled_exc_class()
    while True:
        # Subscribe BEFORE snapshotting so an attach that lands during
        # the dispatch attempt still sets the event we wait on below.
        # ``anyio.Event.set`` is idempotent.
        event = anyio.Event()
        unsub = session.subscribe_elicitation_attach(event.set)
        try:
            clients_in_order = session.elicitation_driver_chain()
            if clients_in_order:
                for client in clients_in_order:
                    # Drain pending notifications so the operator sees
                    # the model's accompanying ``agent_message_chunk``
                    # (the "why" the agent gave) ABOVE the form rather
                    # than after it. Best-effort barrier — see
                    # ``Forwarders.drain`` for the mechanics and the
                    # approval shim for the same pattern.
                    try:
                        await client.drain_notifications()
                    except cancel_exc:
                        raise
                    except Exception as drain_exc:
                        logger.warning(
                            "ACP elicitation drain_notifications failed for "
                            "client %r; proceeding with request anyway: %s",
                            client,
                            drain_exc,
                        )
                    try:
                        response = await client.request_elicitation(request)
                    except cancel_exc:
                        raise
                    except Exception as exc:
                        # Transport failure, target-session mismatch,
                        # or other client-side error. Try the next
                        # client in the fallback chain.
                        logger.debug(
                            "ACP elicitation request failed for client %r; "
                            "trying next: %s",
                            client,
                            exc,
                        )
                        continue
                    else:
                        return _result_from_response(response)
            # No clients attached (yet, or after they all raised).
            # Park until a fresh attach lands. Under exclusive routing
            # this also covers the very first interaction — we don't
            # fall through to panel / console.
            await event.wait()
        finally:
            unsub()


async def acp_handler(request: InputRequest) -> InputResult | None:
    """Route an ``ask_user`` prompt through attached ACP clients.

    Returns:
        - An :class:`InputResult` when an ACP client submitted a
          response. Under exclusive routing the shim *parks* (rather
          than returning ``None``) when no client has attached yet,
          waiting until one does — see
          ``design/acp/elicitation.md`` "Routing policy".
        - ``None`` when ``--acp-server`` was not passed (no
          :class:`AcpServer` is accepting external clients), when no
          active sample / ``acp_transport`` is bound, or when an
          unexpected internal error occurred. The caller
          (``_dispatch_builtin``) then falls through to the panel /
          console flow.

    Hard contract: never propagates a non-cancellation exception to
    the caller. This shim runs synchronously inside ``request_input``
    on the tool-call execution path; an unhandled exception here
    would crash the ``ask_user`` tool call (and could crash the
    eval). On any internal error we log a warning and return ``None``
    so the dispatcher falls back. ``CancelledError`` propagates
    naturally via :func:`acp_guard`'s BaseException semantics —
    sample-level cancel still works.
    """
    with acp_guard(
        "ACP elicitation routing raised; falling back to in-proc input flow"
    ):
        # Deferred import — avoid a registry-init-time cycle through
        # the log subsystem; only fires at actual ``ask_user`` time.
        from inspect_ai.log._samples import sample_active

        # Gate on whether an AcpServer is accepting external clients
        # (set by the ``acp_server`` context manager). When the gate
        # is off, return None so ``_dispatch_builtin`` falls through
        # to the in-proc panel / console.
        if not acp_server_accepting_clients():
            return None
        # Reach for the sample's pinned ``LiveAcpTransport`` rather
        # than ``current_acp_transport()`` — the latter resolves
        # against a ContextVar that's shadowed by ``NoOpAcpTransport``
        # inside any nested ``acp_session()`` block (sub-agent
        # isolation), and the NoOp would park us forever on its
        # never-firing attach subscription with a permanently empty
        # driver chain. Sub-agent isolation is for *event publishing*
        # — human-in-the-loop ``ask_user`` requests must always reach
        # the operator regardless of which agent fired them, so we
        # route through the outermost session. Mirrors the approval
        # shim's entry pattern.
        sample = sample_active()
        if sample is None or sample.acp_transport is None:
            return None
        transport = sample.acp_transport
        elicitation_request = ElicitationRequest(
            message=request.message,
            session_id=transport.session_id,
            requested_schema=request.schema,
        )
        # Mark the sample as parked on a human question so the ACP
        # picker can surface a "pending" column. Ref-counted (not a
        # single-slot save/restore) because tool calls can run
        # concurrently within one sample. See the parallel comment in
        # `approval/_human/acp.py` for the full rationale.
        sample._pending_questions += 1
        try:
            return await _request_from_driver_with_fallback(
                transport, elicitation_request
            )
        finally:
            sample._pending_questions -= 1
    # acp_guard suppressed an exception — fall through to in-proc.
    return None
