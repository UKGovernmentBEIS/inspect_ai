"""Tests for the Phase 6a ACP elicitation input handler.

Mirrors the structure of ``tests/agent/test_acp/test_approval.py``
one-for-one — same single-driver-with-fallback semantics, same
park-and-retry on empty chain, same hard-contract on the public
entry. The shim under test is
:mod:`inspect_ai.input.acp`; the registry plumbing it consumes is
covered by Phase 5's ``test_elicitation.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from acp.schema import (
    AcceptElicitationResponse,
    CancelElicitationResponse,
    DeclineElicitationResponse,
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.transport import ElicitationRequest
from inspect_ai.input._types import InputRequest
from inspect_ai.input.acp import (
    _request_from_driver_with_fallback,
    _result_from_response,
    acp_handler,
)

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


def _input_request(message: str = "What's the secret?") -> InputRequest:
    return InputRequest(message=message, schema=_trivial_schema())


def _elicitation_request(
    session_id: str = "sess-1", message: str = "What's the secret?"
) -> ElicitationRequest:
    return ElicitationRequest(
        message=message,
        session_id=session_id,
        requested_schema=_trivial_schema(),
    )


class _StubSession:
    """Minimal ``_ElicitationRoutingSession`` for the shim.

    Reports a fixed driver chain plus the attach-subscribe primitive.
    Tests that exercise wait-and-retry mutate ``clients`` then call
    ``trigger_attach()`` to fire subscribers — that's the only signal
    the shim uses to re-snapshot the chain.

    Whether ``acp_handler`` parks or falls through is gated on the
    server-running flag (``acp_server_accepting_clients()``), not on
    anything attached to the transport; entry-level tests monkeypatch
    that accessor directly via :func:`patch_acp_server_accepting`.
    """

    def __init__(
        self,
        clients: list[Any] | None = None,
        *,
        session_id: str = "sess-1",
    ) -> None:
        self.clients: list[Any] = list(clients) if clients else []
        self._attach_subscribers: list[Callable[[], None]] = []
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def elicitation_driver_chain(self) -> list[Any]:
        return list(self.clients)

    def subscribe_elicitation_attach(
        self, cb: Callable[[], None]
    ) -> Callable[[], None]:
        self._attach_subscribers.append(cb)

        def _unsub() -> None:
            try:
                self._attach_subscribers.remove(cb)
            except ValueError:
                pass

        return _unsub

    def trigger_attach(self) -> None:
        """Fire subscribers as if a client just attached."""
        for cb in list(self._attach_subscribers):
            cb()


class _StubClient:
    """An ElicitationClient that returns a pre-set response (or raises).

    Tracks ``drain_calls`` and the call sequence so tests can pin the
    drain-then-request ordering per fallback-chain entry.
    """

    def __init__(
        self,
        response: Any | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.response = response
        self.exc = exc
        self.delay = delay
        self.received: list[ElicitationRequest] = []
        self.calls: list[str] = []
        self.drain_calls: int = 0

    async def drain_notifications(self) -> None:
        self.drain_calls += 1
        self.calls.append("drain")

    async def request_elicitation(self, request: ElicitationRequest) -> Any:
        self.received.append(request)
        self.calls.append("request")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        assert self.response is not None
        return self.response


def _accept(content: dict[str, Any] | None = None) -> AcceptElicitationResponse:
    return AcceptElicitationResponse(
        action="accept", content=content or {"answer": "42"}
    )


def _decline() -> DeclineElicitationResponse:
    return DeclineElicitationResponse(action="decline")


def _cancel() -> CancelElicitationResponse:
    return CancelElicitationResponse(action="cancel")


# ---------------------------------------------------------------------------
# _result_from_response — pure mapping
# ---------------------------------------------------------------------------


def test_result_from_response_accept_carries_content() -> None:
    result = _result_from_response(_accept({"answer": "yes"}))
    assert result.outcome == "accepted"
    assert result.content == {"answer": "yes"}


def test_result_from_response_decline_has_no_content() -> None:
    result = _result_from_response(_decline())
    assert result.outcome == "declined"
    assert result.content is None


def test_result_from_response_cancel_has_no_content() -> None:
    result = _result_from_response(_cancel())
    assert result.outcome == "cancelled"
    assert result.content is None


# ---------------------------------------------------------------------------
# _request_from_driver_with_fallback — single-driver semantics
# ---------------------------------------------------------------------------


@skip_if_trio
async def test_fallback_parks_when_chain_is_empty() -> None:
    """Empty chain → park on attach (no silent fallback).

    Under exclusive routing (``--acp-server`` committed the eval to
    ACP), the shim parks on the attach event even on the FIRST
    interaction. Previously it returned ``None`` when no client had
    ever attached, which let the dispatcher fall through to the
    in-proc panel — that fallthrough was the notification-driven
    race documented in ``design/acp/elicitation.md`` "Routing policy".
    """
    survivor = _StubClient(response=_accept({"answer": "first-attach"}))
    session = _StubSession([])

    shim_task = asyncio.create_task(
        _request_from_driver_with_fallback(session, _elicitation_request())
    )
    await asyncio.sleep(0.05)
    assert not shim_task.done()  # parked on subscribe_elicitation_attach

    session.clients = [survivor]
    session.trigger_attach()

    result = await shim_task
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "first-attach"}


@skip_if_trio
async def test_fallback_routes_to_driver_and_drains_first() -> None:
    """Single client → request goes to it; drain precedes request."""
    client = _StubClient(response=_accept({"answer": "yes"}))
    session = _StubSession([client])
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "yes"}
    assert client.drain_calls == 1
    assert client.calls == ["drain", "request"]


@skip_if_trio
async def test_fallback_maps_decline_response() -> None:
    client = _StubClient(response=_decline())
    session = _StubSession([client])
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "declined"
    assert result.content is None


@skip_if_trio
async def test_fallback_maps_cancel_response() -> None:
    client = _StubClient(response=_cancel())
    session = _StubSession([client])
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "cancelled"
    assert result.content is None


@skip_if_trio
async def test_fallback_drain_failure_does_not_skip_request() -> None:
    """If drain raises, log and proceed with the request anyway.

    Best-effort barrier — a drain bug shouldn't silently skip the
    driver and route to a fallback client.
    """

    class _DrainFailingClient(_StubClient):
        async def drain_notifications(self) -> None:
            self.drain_calls += 1
            self.calls.append("drain")
            raise RuntimeError("drain explode")

    client = _DrainFailingClient(response=_accept())
    session = _StubSession([client])
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "accepted"
    assert client.calls == ["drain", "request"]


@skip_if_trio
async def test_fallback_chain_advances_on_per_client_exception() -> None:
    """First client raises → next is tried; first success returns."""
    broken = _StubClient(exc=ConnectionError("disconnected"))
    survivor = _StubClient(response=_accept({"answer": "ok"}))
    session = _StubSession([broken, survivor])
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "ok"}
    # Both clients drained; both were dispatched-to; ordering pinned.
    assert broken.calls == ["drain", "request"]
    assert survivor.calls == ["drain", "request"]


@skip_if_trio
async def test_fallback_re_parks_when_chain_empties_after_attach() -> None:
    """After a client attaches then disconnects, the shim parks again.

    Covers the "operator was here, dropped, came back" sequence which
    is independent of the first-interaction parking (covered by
    ``test_fallback_parks_when_chain_is_empty``). Under the unified
    exclusive-routing policy both paths share the same wait — this
    test just exercises the second iteration of the loop.
    """
    first = _StubClient(exc=ConnectionError("first dropped"))
    survivor = _StubClient(response=_accept({"answer": "after-rebind"}))
    session = _StubSession([first])

    shim_task = asyncio.create_task(
        _request_from_driver_with_fallback(session, _elicitation_request())
    )
    # The shim tries ``first``, it raises, chain exhausts, shim parks.
    await asyncio.sleep(0.05)
    assert not shim_task.done()

    session.clients = [survivor]
    session.trigger_attach()

    result = await shim_task
    assert result is not None
    assert result.content == {"answer": "after-rebind"}


@skip_if_trio
async def test_fallback_no_lost_attach_signal_during_snapshot() -> None:
    """Attach that fires during chain snapshot is not lost.

    The shim must subscribe BEFORE snapshotting the chain — otherwise
    an attach landing in between has no subscriber and the shim parks
    forever despite a live client being present. Pinned regression
    of the analogous race the approval shim guards against.
    """
    survivor = _StubClient(response=_accept())

    class _RacingSession(_StubSession):
        def __init__(self) -> None:
            super().__init__([])
            self._first_snapshot = True

        def elicitation_driver_chain(self) -> list[Any]:
            # First call: empty AND simulate a concurrent attach
            # landing before the shim gets to wait.
            if self._first_snapshot:
                self._first_snapshot = False
                self.clients = [survivor]
                self.trigger_attach()
                return []
            return list(self.clients)

    session = _RacingSession()
    result = await _request_from_driver_with_fallback(session, _elicitation_request())
    assert result is not None
    assert result.outcome == "accepted"
    assert len(survivor.received) == 1


@skip_if_trio
async def test_fallback_re_parks_cleanly_on_spurious_attach() -> None:
    """Spurious attach (client gone before reach) re-parks; no busy spin."""
    survivor = _StubClient(response=_accept())
    session = _StubSession([])

    shim_task = asyncio.create_task(
        _request_from_driver_with_fallback(session, _elicitation_request())
    )
    await asyncio.sleep(0.05)

    # Two spurious wakes — empty chain, nothing to dispatch.
    session.trigger_attach()
    await asyncio.sleep(0.05)
    session.trigger_attach()
    await asyncio.sleep(0.05)
    assert not shim_task.done()

    # Real attach.
    session.clients = [survivor]
    session.trigger_attach()
    result = await shim_task
    assert result is not None
    assert result.outcome == "accepted"


# ---------------------------------------------------------------------------
# acp_handler — top-level entry
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_sample_active(monkeypatch):
    """Patch ``sample_active`` to return a stub sample with ``acp_transport``.

    Mirrors the approval-test fixture of the same name. The
    elicitation shim reaches for ``sample_active().acp_transport``
    (the outermost ``LiveAcpTransport`` pinned at sample startup)
    rather than ``current_acp_transport()`` — sub-agent isolation
    shadows the ContextVar with a ``NoOpAcpTransport``, and the NoOp
    would mis-route human-in-the-loop traffic.

    Pass ``None`` to simulate "no acp_transport on the sample"; pass
    ``"no-sample"`` to simulate ``sample_active() is None``.
    """

    def _patch(session: Any) -> None:
        if session == "no-sample":
            monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: None)
            return
        sample = MagicMock()
        sample.acp_transport = session
        monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)

    return _patch


@pytest.fixture
def acp_server_running(monkeypatch):
    """Patch ``acp_server_accepting_clients`` to ``True`` for entry tests.

    The real accessor reads a ContextVar set by the ``acp_server``
    context manager and defaults to ``False``. Entry-level tests run
    outside that scope, so the gate would deny without this patch.
    Use this fixture for tests that exercise the in-ACP-mode path;
    omit it for tests that explicitly want the ``return None`` /
    fall-through path.
    """
    monkeypatch.setattr(
        "inspect_ai.input.acp.acp_server_accepting_clients", lambda: True
    )


@skip_if_trio
async def test_entry_returns_none_when_acp_server_not_running(
    patch_sample_active,
) -> None:
    """``--acp-server`` not active → entry returns None so dispatcher falls back.

    Under exclusive routing, ``acp_handler`` only returns ``None``
    when the ``acp_server`` context manager hasn't flipped
    :func:`acp_server_accepting_clients` to ``True``. The default
    ContextVar value is ``False``, so an entry-level test with no
    explicit patching exercises this case directly — no extra fixture
    needed. When the server IS running, the shim parks instead —
    covered by :func:`test_entry_parks_when_live_with_no_clients`.
    """
    patch_sample_active(_StubSession([]))
    result = await acp_handler(_input_request())
    assert result is None


@skip_if_trio
async def test_entry_returns_none_when_no_active_sample(
    acp_server_running, monkeypatch
) -> None:
    """``sample_active()`` returns None → entry returns None.

    The shim only routes when there's a sample to anchor the
    outermost transport. With no active sample we let the dispatcher
    fall through. This is the path that previously hung — the old
    predicate reached for ``current_acp_transport()`` which would
    return a NoOp singleton and park forever on its never-firing
    attach subscription.
    """
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: None)
    result = await acp_handler(_input_request())
    assert result is None


@skip_if_trio
async def test_entry_returns_none_when_sample_has_no_acp_transport(
    patch_sample_active, acp_server_running
) -> None:
    """``sample.acp_transport`` is None → entry returns None.

    Mirrors the approval shim's ``test_entry_returns_none_when_no_acp_session``.
    """
    patch_sample_active(None)
    result = await acp_handler(_input_request())
    assert result is None


@skip_if_trio
async def test_entry_parks_when_live_with_no_clients(
    patch_sample_active,
    acp_server_running,
) -> None:
    """ACP server running + no clients → entry parks, no fallback.

    Pinned regression of the notification race: previously
    ``acp_handler`` returned ``None`` whenever
    ``has_ever_had_elicitation_client()`` was ``False``, which let the
    panel grab the future before the operator could attach an ACP
    client. Under exclusive routing the shim parks until a client
    arrives — the in-proc panel never sees this interaction.
    """
    survivor = _StubClient(response=_accept({"answer": "after-attach"}))
    session = _StubSession([])
    patch_sample_active(session)

    shim_task = asyncio.create_task(acp_handler(_input_request()))
    await asyncio.sleep(0.05)
    assert not shim_task.done()  # parked

    session.clients = [survivor]
    session.trigger_attach()

    result = await shim_task
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "after-attach"}


@skip_if_trio
async def test_entry_routes_to_attached_client_with_session_id(
    patch_sample_active,
    acp_server_running,
) -> None:
    """Client attached → request routes through it; session_id is set from transport."""
    client = _StubClient(response=_accept({"answer": "yes"}))
    session = _StubSession([client], session_id="sess-xyz")
    patch_sample_active(session)

    result = await acp_handler(_input_request("Pick one"))
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "yes"}
    # The shim wraps the InputRequest into an ElicitationRequest with
    # the transport's session_id pinned in place.
    assert len(client.received) == 1
    sent = client.received[0]
    assert sent.message == "Pick one"
    assert sent.session_id == "sess-xyz"
    assert sent.requested_schema.properties is not None
    assert "answer" in sent.requested_schema.properties


@skip_if_trio
async def test_entry_returns_none_when_shim_guard_suppresses(
    patch_sample_active, acp_server_running, monkeypatch
) -> None:
    """An internal bug in the dispatch loop must not crash the tool call.

    The hard contract: ``acp_guard`` catches any non-cancellation
    exception, logs, and the entry returns ``None`` so the caller
    falls through to the in-proc panel / console. Force the failure
    by patching the dispatch helper to raise.
    """
    patch_sample_active(_StubSession([_StubClient(response=_accept())]))

    async def _explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("unexpected shim bug")

    monkeypatch.setattr(
        "inspect_ai.input.acp._request_from_driver_with_fallback", _explode
    )
    result = await acp_handler(_input_request())
    assert result is None
