"""Phase 7 tests for the ``ActiveSample.acp_session`` registration lifecycle.

The TUI runs in a sibling task to the agent and cannot reach the
ContextVar-installed :class:`AcpSession` directly. Phase 7 publishes
the live session on the current :class:`ActiveSample` so the TUI can
read ``sample.acp_session`` to gate its Interrupt button and dispatch
``cancel_current_turn`` / ``submit_user_message`` from outside the
agent task.

These tests cover the registration path independently of the TUI.
"""

from inspect_ai.agent._acp._session import (
    _NOOP_SESSION_ID,
    _LiveAcpSession,
    acp_session,
)
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._samples import ActiveSample
from inspect_ai.log._samples import _sample_active as samples_var
from inspect_ai.log._transcript import Transcript


def _make_active_sample() -> ActiveSample:
    """Build a bare-bones ActiveSample suitable for these unit tests."""
    return ActiveSample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        sandboxes={},
    )


async def test_acp_session_field_is_none_without_acp_session() -> None:
    """Baseline: an ActiveSample never touched by acp_session() has None."""
    active = _make_active_sample()
    assert active.acp_session is None


async def test_live_acp_session_registers_on_active_sample() -> None:
    """Entering acp_session() inside an active sample context publishes the session."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as acp:
            assert active.acp_session is acp
            assert acp.session_id != _NOOP_SESSION_ID
    finally:
        samples_var.reset(token)


async def test_acp_session_field_cleared_on_exit() -> None:
    """Exiting acp_session() must clear the field."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session():
            assert active.acp_session is not None
        assert active.acp_session is None
    finally:
        samples_var.reset(token)


async def test_sub_agent_shadow_does_not_clobber_outer_registration() -> None:
    """A nested no-op shadow session must not overwrite the outer live session."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as outer:
            assert active.acp_session is outer
            async with acp_session() as inner:
                # Inner is a no-op shadow because outer is already live.
                assert inner.session_id == _NOOP_SESSION_ID
                # Outer registration is still in place.
                assert active.acp_session is outer
            # After inner exits, outer is still registered.
            assert active.acp_session is outer
        assert active.acp_session is None
    finally:
        samples_var.reset(token)


async def test_noop_session_does_not_touch_active_sample() -> None:
    """A no-op session must never write to ActiveSample.acp_session.

    Two scenarios:
    1. No active sample context at all → no error, field stays unset.
    2. Nested inside a live session → outer live registration unchanged.
    """
    # Scenario 1: no active sample at all. Should not error.
    token = samples_var.set(None)
    try:
        async with acp_session() as acp:
            # We're not inside an active sample, so there's nothing
            # to write to. The session should still function.
            assert acp.session_id != _NOOP_SESSION_ID
    finally:
        samples_var.reset(token)

    # Scenario 2: nested no-op leaves outer registration alone.
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as outer:
            async with acp_session():
                # field still points at outer
                assert active.acp_session is outer
    finally:
        samples_var.reset(token)


async def test_aexit_identity_guard_protects_active_registration() -> None:
    """A stale `__aexit__` from a session A must not clear an active B registration."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        session_a = _LiveAcpSession()
        session_b = _LiveAcpSession()
        # Enter A first so it registers on active.
        await session_a.__aenter__()
        assert active.acp_session is session_a
        # Now overwrite the registration with B (simulating B winning a race).
        active.acp_session = session_b
        # Calling A's exit must NOT clear the field because B is registered.
        await session_a.__aexit__(None, None, None)
        assert active.acp_session is session_b
        # Clean up B properly.
        await session_b.__aexit__(None, None, None)
        # B's exit should clear its own registration.
        assert active.acp_session is None
    finally:
        samples_var.reset(token)
