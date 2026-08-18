"""Tests for the Phase 5 ACP elicitation transport.

Covers the wire surface added in this phase — capability gating,
``ConnectionHandler.request_elicitation`` dispatch, response-action
parsing, and the elicitation client registry's fan-out via
``mark_active_session_client``.

The Phase 6 driver-fallback shim (``_input/acp.py``) is not yet
written; tests that exercise the full dispatch loop with fallback
on disconnect arrive in that phase. The pure driver-chain mechanics
are already covered by ``test_session.py`` via the shared
``_ClientDriverRegistry`` base.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.schema import (
    AcceptElicitationResponse,
    CancelElicitationResponse,
    ClientCapabilities,
    DeclineElicitationResponse,
    ElicitationCapabilities,
    ElicitationFormCapabilities,
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.connection import (
    ConnectionHandler,
    _parse_elicitation_response,
)
from inspect_ai.agent._acp.transport import ElicitationRequest, acp_session
from inspect_ai.agent._acp.transport_noop import NoOpAcpTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trivial_schema() -> ElicitationSchema:
    return ElicitationSchema(
        properties={
            "answer": ElicitationStringPropertySchema(type="string", title="Answer")
        },
        required=["answer"],
    )


def _form_request(
    session_id: str = "s1",
    message: str = "What's the API key?",
    tool_call_id: str | None = None,
) -> ElicitationRequest:
    return ElicitationRequest(
        message=message,
        session_id=session_id,
        requested_schema=_trivial_schema(),
        tool_call_id=tool_call_id,
    )


class _StubElicitationClient:
    """An ElicitationClient returning a pre-set response (or raising).

    Tracks ``drain_calls`` so tests can assert the shim invokes the
    drain barrier before each ``request_elicitation`` once Phase 6
    lands. Used here for direct registry / dispatch tests.
    """

    def __init__(
        self,
        response: Any | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.response = response
        self.exc = exc
        self.received: list[ElicitationRequest] = []
        self.drain_calls: int = 0

    async def drain_notifications(self) -> None:
        self.drain_calls += 1

    async def request_elicitation(self, request: ElicitationRequest) -> Any:
        self.received.append(request)
        if self.exc is not None:
            raise self.exc
        assert self.response is not None
        return self.response


# ---------------------------------------------------------------------------
# _parse_elicitation_response — discriminator + malformed payloads
# ---------------------------------------------------------------------------


def test_parse_accept_response_with_content() -> None:
    raw = {"action": "accept", "content": {"answer": "42"}}
    parsed = _parse_elicitation_response(raw)
    assert isinstance(parsed, AcceptElicitationResponse)
    assert parsed.action == "accept"
    assert parsed.content == {"answer": "42"}


def test_parse_decline_response_minimal() -> None:
    raw = {"action": "decline"}
    parsed = _parse_elicitation_response(raw)
    assert isinstance(parsed, DeclineElicitationResponse)
    assert parsed.action == "decline"


def test_parse_cancel_response_minimal() -> None:
    raw = {"action": "cancel"}
    parsed = _parse_elicitation_response(raw)
    assert isinstance(parsed, CancelElicitationResponse)
    assert parsed.action == "cancel"


def test_parse_unknown_action_raises() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        _parse_elicitation_response({"action": "ignore"})


def test_parse_non_dict_payload_raises() -> None:
    with pytest.raises(ValueError, match="must be a dict"):
        _parse_elicitation_response(["accept"])


# ---------------------------------------------------------------------------
# Capability gating — ConnectionState reflects ``initialize`` payload
# ---------------------------------------------------------------------------


def _capabilities(*, form: bool) -> ClientCapabilities:
    return ClientCapabilities(
        elicitation=ElicitationCapabilities(
            form=ElicitationFormCapabilities() if form else None
        ),
    )


@skip_if_trio
@pytest.mark.anyio
async def test_initialize_captures_elicitation_form_capability_true() -> None:
    handler = ConnectionHandler()
    await handler.initialize(
        protocol_version=1, client_capabilities=_capabilities(form=True)
    )
    assert handler.state.client_supports_elicitation_form is True


@skip_if_trio
@pytest.mark.anyio
async def test_initialize_captures_elicitation_form_capability_false() -> None:
    handler = ConnectionHandler()
    await handler.initialize(
        protocol_version=1, client_capabilities=_capabilities(form=False)
    )
    assert handler.state.client_supports_elicitation_form is False


@skip_if_trio
@pytest.mark.anyio
async def test_initialize_missing_capabilities_leaves_flag_false() -> None:
    handler = ConnectionHandler()
    await handler.initialize(protocol_version=1, client_capabilities=None)
    assert handler.state.client_supports_elicitation_form is False


# ---------------------------------------------------------------------------
# Elicitation registry — basic semantics via LiveAcpTransport surface
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_elicitation_attach_and_notify_make_client_visible() -> None:
    async with acp_session() as acp:
        client = _StubElicitationClient()
        # Pending only (no notify yet) → still invisible to driver chain.
        unsub = acp.attach_elicitation_client(client)
        assert acp.elicitation_driver_chain() == []
        assert acp.has_elicitation_clients() is False
        # After notify, client is ready and visible.
        acp.notify_elicitation_attach(client)
        assert acp.elicitation_driver_chain() == [client]
        assert acp.has_elicitation_clients() is True
        unsub()
        assert acp.elicitation_driver_chain() == []
        assert acp.has_elicitation_clients() is False


@skip_if_trio
@pytest.mark.anyio
async def test_elicitation_driver_chain_orders_driver_first() -> None:
    async with acp_session() as acp:
        a = _StubElicitationClient()
        b = _StubElicitationClient()
        c = _StubElicitationClient()
        for client in (a, b, c):
            acp.attach_elicitation_client(client)
            acp.notify_elicitation_attach(client)
        acp.mark_active_session_client(b)
        assert acp.elicitation_driver_chain() == [b, a, c]
        acp.mark_active_session_client(c)
        assert acp.elicitation_driver_chain() == [c, a, b]


@skip_if_trio
@pytest.mark.anyio
async def test_mark_active_session_client_fans_out_across_registries() -> None:
    """A single ``mark_active_session_client`` call promotes the same client.

    Promotes across BOTH the approver and elicitation registries when the
    connection is attached to both — the aggregator's whole point.
    """
    from inspect_ai.agent._acp.transport_live import _ElicitationClientRegistry

    # Use a small concrete client that satisfies both Protocols. The
    # production ConnectionHandler does this naturally; here we just
    # need an object identity that's accepted by both registries.
    class _DualClient:
        async def request_permission(self, request: Any) -> Any: ...

        async def drain_notifications(self) -> None:  # pragma: no cover
            return None

        async def request_elicitation(self, request: Any) -> Any: ...

    async with acp_session() as acp:
        a = _DualClient()
        b = _DualClient()
        # Attach + notify both clients on BOTH registries.
        for client in (a, b):
            acp.attach_approver_client(client)
            acp.notify_approver_attach(client)
            acp.attach_elicitation_client(client)
            acp.notify_elicitation_attach(client)
        # Unified mark_active promotes ``b`` everywhere.
        acp.mark_active_session_client(b)
        assert acp.approver_driver_chain() == [b, a]
        assert acp.elicitation_driver_chain() == [b, a]
        # And the same call is safe when the client is in only ONE
        # registry (other registry's mark_active no-ops on miss).
        approver_only = _DualClient()
        acp.attach_approver_client(approver_only)
        acp.notify_approver_attach(approver_only)
        acp.mark_active_session_client(approver_only)
        # Driver first, then remaining ready clients in attachment order.
        assert acp.approver_driver_chain() == [approver_only, a, b]
        # elicitation chain unchanged because approver_only isn't there;
        # its `mark_active` is a no-op on the elicitation registry,
        # so the prior driver (``b``) stays in place.
        assert acp.elicitation_driver_chain() == [b, a]
        # Sanity: standalone _ElicitationClientRegistry resolves the
        # generic typing.
        assert isinstance(
            acp._clients.elicitations,  # type: ignore[attr-defined]
            _ElicitationClientRegistry,
        )


@skip_if_trio
@pytest.mark.anyio
async def test_session_exit_clears_elicitation_registry() -> None:
    """The aggregator's ``clear`` drops elicitation registrations too."""
    closed = None
    async with acp_session() as acp:
        client = _StubElicitationClient()
        acp.attach_elicitation_client(client)
        acp.notify_elicitation_attach(client)
        assert acp.has_elicitation_clients() is True
        closed = acp
    # Outside the context, both registries are cleared.
    assert closed.has_elicitation_clients() is False
    assert closed.elicitation_driver_chain() == []


@skip_if_trio
@pytest.mark.anyio
async def test_noop_transport_elicitation_methods_are_safe() -> None:
    noop = NoOpAcpTransport()
    client = _StubElicitationClient()
    assert noop.has_elicitation_clients() is False
    assert noop.has_ever_had_elicitation_client() is False
    assert noop.elicitation_driver_chain() == []
    unsub = noop.attach_elicitation_client(client)
    assert noop.has_elicitation_clients() is False
    noop.mark_active_session_client(client)
    noop.notify_elicitation_attach(client)
    unsub()  # no-op, no raise
    cb_unsub = noop.subscribe_elicitation_attach(lambda: None)
    cb_unsub()  # no-op, no raise


# ---------------------------------------------------------------------------
# ConnectionHandler.request_elicitation — wire dispatch
# ---------------------------------------------------------------------------


def _wire_send_request_stub(
    response: dict[str, Any],
) -> tuple[MagicMock, Any]:
    """Build a fake acp Connection that captures one send_request call."""
    fake_conn = MagicMock()

    async def fake_send_request(method: str, payload: dict[str, Any]) -> dict[str, Any]:
        fake_conn.last_method = method
        fake_conn.last_payload = payload
        return response

    fake_conn.send_request = fake_send_request
    return fake_conn, fake_send_request


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_dispatches_correct_method_and_payload() -> None:
    """``request_elicitation`` emits the standard ACP wire shape.

    Sends ``elicitation/create`` with a flat
    ``{message, mode, sessionId, requestedSchema}`` object — the
    canonical ACP 0.10 form-session wire payload — and parses the
    ``accept`` response.
    """
    from inspect_ai.agent._acp.connection import Bound

    handler = ConnectionHandler()
    handler.state.binding = Bound(target_session_id="s1", wire_session_id="s1")
    fake_conn, _ = _wire_send_request_stub(
        {"action": "accept", "content": {"answer": "42"}}
    )
    handler.connection = fake_conn

    req = _form_request()
    response = await handler.request_elicitation(req)

    assert fake_conn.last_method == "elicitation/create"
    # Standard ACP wire payload: flat, no nested mode wrapper, schema
    # serialized by alias (camelCase) with null fields omitted.
    schema_dump = req.requested_schema.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert fake_conn.last_payload == {
        "message": req.message,
        "mode": "form",
        "sessionId": "s1",
        "requestedSchema": schema_dump,
    }
    assert isinstance(response, AcceptElicitationResponse)
    assert response.content == {"answer": "42"}


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_includes_tool_call_id_when_set() -> None:
    """Optional ``toolCallId`` is included on the wire when present."""
    from inspect_ai.agent._acp.connection import Bound

    handler = ConnectionHandler()
    handler.state.binding = Bound(target_session_id="s1", wire_session_id="s1")
    fake_conn, _ = _wire_send_request_stub({"action": "decline"})
    handler.connection = fake_conn

    req = _form_request(tool_call_id="call-xyz")
    await handler.request_elicitation(req)

    assert fake_conn.last_payload["toolCallId"] == "call-xyz"


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_omits_tool_call_id_when_unset() -> None:
    """Absent ``toolCallId`` stays absent — no explicit null on the wire.

    Echoes the ACP convention (and the existing ``request_permission``
    behavior): optional fields are omitted, not nulled.
    """
    from inspect_ai.agent._acp.connection import Bound

    handler = ConnectionHandler()
    handler.state.binding = Bound(target_session_id="s1", wire_session_id="s1")
    fake_conn, _ = _wire_send_request_stub({"action": "decline"})
    handler.connection = fake_conn

    await handler.request_elicitation(_form_request())  # tool_call_id=None
    assert "toolCallId" not in fake_conn.last_payload


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_rewrites_session_id_in_picker_mode() -> None:
    """In picker mode the wire ``sessionId`` is the synthetic control id.

    Mirrors ``request_permission`` — the request carries the target
    sessionId (the canonical id the agent loop sees), but the client
    knows the connection by its picker-minted ``wire_session_id`` and
    would otherwise reject the prompt as cross-session traffic.
    """
    from inspect_ai.agent._acp.connection import Bound

    handler = ConnectionHandler()
    handler.state.binding = Bound(
        target_session_id="target-uuid",
        wire_session_id="wire-uuid",
    )
    fake_conn, _ = _wire_send_request_stub({"action": "cancel"})
    handler.connection = fake_conn

    # Request is built against the target sessionId; the rewrite
    # happens inside request_elicitation.
    await handler.request_elicitation(_form_request(session_id="target-uuid"))
    assert fake_conn.last_payload["sessionId"] == "wire-uuid"


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_raises_on_target_session_mismatch() -> None:
    """A request for a different target than we're bound to raises.

    Covers the race where the connection rebinds (or unbinds and
    rebinds to a different target) between the Phase 6 shim
    snapshotting the driver chain and this method being invoked. The
    shim's driver-fallback loop treats the ConnectionError as "try the
    next client" so the elicitation isn't silently routed to the
    wrong session.
    """
    from inspect_ai.agent._acp.connection import Bound

    handler = ConnectionHandler()
    handler.state.binding = Bound(
        target_session_id="bound-target", wire_session_id="bound-target"
    )
    handler.connection = MagicMock()

    req = _form_request(session_id="other-target")
    with pytest.raises(ConnectionError, match="target mismatch"):
        await handler.request_elicitation(req)


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_raises_when_unbound() -> None:
    """An unbound connection raises so the driver-fallback shim moves on."""
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    with pytest.raises(ConnectionError, match="not bound"):
        await handler.request_elicitation(_form_request())


@skip_if_trio
@pytest.mark.anyio
async def test_request_elicitation_raises_when_connection_missing() -> None:
    """A missing connection raises so the driver-fallback shim moves on."""
    handler = ConnectionHandler()
    # connection attribute defaults to None; explicit for clarity.
    handler.connection = None
    with pytest.raises(ConnectionError, match="not attached"):
        await handler.request_elicitation(_form_request())
