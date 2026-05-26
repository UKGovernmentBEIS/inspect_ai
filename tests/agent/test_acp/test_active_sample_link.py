"""Phase 7 tests for the ``ActiveSample.acp_transport`` registration lifecycle.

The TUI runs in a sibling task to the agent and cannot reach the
ContextVar-installed :class:`AcpTransport` directly. Phase 7 publishes
the live session on the current :class:`ActiveSample` so the TUI can
read ``sample.acp_transport`` to gate its Interrupt button and dispatch
``cancel_current_turn`` / ``submit_user_message`` from outside the
agent task.

These tests cover the registration path independently of the TUI.
"""

from unittest.mock import MagicMock

from inspect_ai.agent._acp.transport import _NOOP_SESSION_ID, acp_session
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._samples import ActiveSample, active_sample
from inspect_ai.log._samples import _sample_active as samples_var
from inspect_ai.log._transcript import Transcript
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer
from inspect_ai.util._limit import LimitExceededError


def _make_active_sample() -> ActiveSample:
    """Build a bare-bones ActiveSample suitable for these unit tests."""
    return ActiveSample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(id=1, input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        sandboxes={},
        checkpointer=_NoopCheckpointer(),
        eval_id="eval-1",
    )


async def test_acp_session_field_is_none_without_acp_session() -> None:
    """Baseline: an ActiveSample never touched by acp_session() has None."""
    active = _make_active_sample()
    assert active.acp_transport is None


async def test_live_acp_session_registers_on_active_sample() -> None:
    """Entering acp_session() inside an active sample context publishes the session."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as acp:
            assert active.acp_transport is acp
            assert acp.session_id != _NOOP_SESSION_ID
    finally:
        samples_var.reset(token)


async def test_acp_session_field_persists_post_exit_until_finalize() -> None:
    """Split-phase: ``__aexit__`` leaves the binding intact for scoring.

    The agent's ``async with acp_session()`` block exits *before* the
    task runner's scoring + logging block runs. We want scoring events
    to still reach attached ACP clients via the bound session — so
    ``__aexit__`` keeps ``ActiveSample.acp_transport`` pointing at the
    session. The eventual full teardown runs via :meth:`finalize`,
    invoked by ``active_sample().__aexit__`` when the sample is fully
    done. Here we drive ``finalize`` by hand to pin the contract.
    """
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as acp:
            assert active.acp_transport is acp
        # Post-agent: binding still alive so scoring events reach clients.
        assert active.acp_transport is acp
        # finalize() is what active_sample() calls during teardown.
        assert isinstance(acp, LiveAcpTransport)
        await acp.finalize()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


async def test_sub_agent_shadow_does_not_clobber_outer_registration() -> None:
    """A nested no-op shadow session must not overwrite the outer live session.

    With split-phase teardown, the outer session's binding persists
    past the outer ``async with`` exit (so scoring events still
    reach attached clients). Cleared by ``finalize()`` here to match
    what ``active_sample()`` would do at sample-end.
    """
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as outer:
            assert active.acp_transport is outer
            async with acp_session() as inner:
                # Inner is a no-op shadow because outer is already live.
                assert inner.session_id == _NOOP_SESSION_ID
                # Outer registration is still in place.
                assert active.acp_transport is outer
            # After inner exits, outer is still registered.
            assert active.acp_transport is outer
        # Outer exited split-phase — binding survives until finalize.
        assert active.acp_transport is outer
        assert isinstance(outer, LiveAcpTransport)
        await outer.finalize()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


async def test_noop_session_does_not_touch_active_sample() -> None:
    """A no-op session must never write to ActiveSample.acp_transport.

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
                assert active.acp_transport is outer
    finally:
        samples_var.reset(token)


async def test_aexit_unbound_session_does_full_teardown() -> None:
    """An unbound session (no ActiveSample) tears down fully on ``__aexit__``.

    The split-phase entry only triggers when bound. Standalone use
    (tests that construct ``LiveAcpTransport()`` without an
    ActiveSample) preserves the original behavior: ``__aexit__`` is
    the single termination signal.
    """
    # No active sample registered.
    token = samples_var.set(None)
    try:
        session = LiveAcpTransport()
        session._attachable_override = True
        await session.__aenter__()
        stream = session.attach()
        await session.__aexit__(None, None, None)
        # Unbound exit ran full teardown: subscribers see EOF.
        import anyio
        import pytest

        with pytest.raises(anyio.EndOfStream):
            await stream.receive()
    finally:
        samples_var.reset(token)


async def test_finalize_idempotent() -> None:
    """``finalize()`` is idempotent — repeat calls no-op cleanly."""
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as acp:
            assert active.acp_transport is acp
        assert isinstance(acp, LiveAcpTransport)
        await acp.finalize()
        assert active.acp_transport is None
        # Re-finalize: no error, still cleared.
        await acp.finalize()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


async def test_post_agent_subscribers_still_receive_published_updates() -> None:
    """Bound split-phase exit keeps the pubsub alive for scoring events.

    Subscribers attached BEFORE the agent's exit must continue to
    receive publishes (mirroring the ``ScoreEvent`` path the live
    router uses internally). EOF only fires when ``finalize()`` runs.
    """
    import anyio
    import pytest

    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as acp:
            stream = acp.attach()
            # During the agent's scope: standard publish/receive works.
            acp.publish({"k": "v1"})
            assert await stream.receive() == {"k": "v1"}
        # After split-phase exit: still alive, still bound.
        assert active.acp_transport is acp
        acp.publish({"k": "v2"})
        assert await stream.receive() == {"k": "v2"}
        # finalize is what closes things.
        assert isinstance(acp, LiveAcpTransport)
        await acp.finalize()
        with pytest.raises(anyio.EndOfStream):
            await stream.receive()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


async def test_consecutive_agents_handover_finalizes_predecessor() -> None:
    """Two agents in the same sample: B's __aenter__ finalizes A's parked session.

    Solver pattern: ``react()`` runs, exits, then another agent runs
    before scoring. Without predecessor-finalize, A's session would
    stay parked with router + pubsub attached forever (orphaned by
    B's binding overwrite). The handover is verified by checking
    that A's subscriber sees EOF the moment B enters.
    """
    import anyio
    import pytest

    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        async with acp_session() as agent_a:
            stream_a = agent_a.attach()
            session_a_id = agent_a.session_id
        # A is parked (split-phase). Now B enters.
        async with acp_session() as agent_b:
            assert agent_b.session_id != session_a_id
            assert active.acp_transport is agent_b
            # A's subscriber saw EOF when B's __aenter__ finalized A.
            with pytest.raises(anyio.EndOfStream):
                await stream_a.receive()
        # B is now parked. Finalize manually (active_sample would
        # ordinarily do this).
        assert isinstance(agent_b, LiveAcpTransport)
        await agent_b.finalize()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


async def test_aexit_identity_guard_protects_active_registration() -> None:
    """A stale `__aexit__` from a session A must not clear an active B registration.

    With the split-phase teardown, neither ``__aexit__`` branch clears
    a *foreign* registration. ``finalize()`` carries an ``is self``
    guard so calling it on a session whose registration has been
    overwritten leaves the new registration alone.
    """
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        session_a = LiveAcpTransport()
        session_a._attachable_override = True
        session_b = LiveAcpTransport()
        session_b._attachable_override = True
        # Enter A first so it registers on active.
        await session_a.__aenter__()
        assert active.acp_transport is session_a
        # Now overwrite the registration with B (simulating B winning a race).
        active.acp_transport = session_b
        # A's __aexit__ + finalize must NOT clear the field — B owns it.
        await session_a.__aexit__(None, None, None)
        await session_a.finalize()
        assert active.acp_transport is session_b
        # Clean up B properly (bound → split-phase exit, then finalize).
        await session_b.__aexit__(None, None, None)
        await session_b.finalize()
        assert active.acp_transport is None
    finally:
        samples_var.reset(token)


# ---------------------------------------------------------------------------
# Lifecycle callback hooks: on_complete + on_interrupt
# ---------------------------------------------------------------------------
#
# ActiveSample exposes two callback slots that whoever binds the sample
# can register. The live ACP session uses them so log/_samples.py doesn't
# need to import or call into the ACP layer directly: instead, the
# session registers its own teardown + cancel cleanup at __aenter__ time
# and the runner just fires whatever is registered.


async def test_live_acp_session_registers_lifecycle_callbacks() -> None:
    """Entering acp_session() inside an active sample wires both hooks.

    Bound methods are re-created per attribute access, so identity is
    checked via ``__self__`` (the session instance) and ``__func__``
    (the unbound method) rather than ``is acp.finalize`` (which would
    always be False).
    """
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        assert active.on_complete is None
        assert active.on_interrupt is None
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            assert active.on_complete is not None
            assert active.on_complete.__self__ is acp
            assert active.on_complete.__func__ is LiveAcpTransport.finalize
            assert active.on_interrupt is not None
            assert active.on_interrupt.__self__ is acp
            assert active.on_interrupt.__func__ is LiveAcpTransport.cancel_current_turn
        # Bound exit parks — callbacks survive until finalize().
        assert active.on_complete is not None
        assert active.on_interrupt is not None
        await acp.finalize()
        assert active.on_complete is None
        assert active.on_interrupt is None
    finally:
        samples_var.reset(token)


async def test_finalize_identity_guard_protects_callbacks() -> None:
    """A stale finalize must not clear callbacks owned by a successor.

    Mirrors :func:`test_aexit_identity_guard_protects_active_registration`
    for the two new callback slots — the same ``is self`` guard in
    ``finalize`` gates all three writes (acp_session, on_complete,
    on_interrupt) so a stale predecessor can't strip a live successor.
    """
    active = _make_active_sample()
    token = samples_var.set(active)
    try:
        session_a = LiveAcpTransport()
        session_a._attachable_override = True
        session_b = LiveAcpTransport()
        session_b._attachable_override = True
        await session_a.__aenter__()
        # B wins a race and takes over (also rewriting callbacks).
        active.acp_transport = session_b
        active.on_complete = session_b.finalize
        active.on_interrupt = session_b.cancel_current_turn
        # A's finalize must not clear B's slots.
        await session_a.__aexit__(None, None, None)
        await session_a.finalize()
        assert active.acp_transport is session_b
        # B's bound methods compared via __self__ + __func__ (see the
        # registration test for the rationale).
        assert active.on_complete is not None
        assert active.on_complete.__self__ is session_b  # type: ignore[attr-defined]
        assert active.on_interrupt is not None
        assert active.on_interrupt.__self__ is session_b  # type: ignore[attr-defined]
        # Clean up B.
        await session_b.__aexit__(None, None, None)
        await session_b.finalize()
        assert active.acp_transport is None
        assert active.on_complete is None
        assert active.on_interrupt is None
    finally:
        samples_var.reset(token)


def test_sample_interrupt_fires_on_interrupt_hook_with_user_cancel_cause() -> None:
    """`interrupt()` calls the registered hook with cause="user_cancel".

    Synthetic ``tg`` so we don't have to actually take down a task
    group; the contract being tested is "the hook fires with the
    right cause AND the cancel still fires."
    """
    sample = _make_active_sample()
    sample.tg = MagicMock()
    causes: list[str] = []
    sample.on_interrupt = lambda cause: causes.append(cause)
    sample.interrupt("score")
    assert causes == ["user_cancel"]
    sample.tg.cancel_scope.cancel.assert_called_once_with()


def test_sample_limit_exceeded_fires_on_interrupt_hook_with_limit_cause() -> None:
    """`limit_exceeded()` fires the hook with cause="limit", NOT "user_cancel".

    A token / time / cost / message limit hit is system-driven, not
    operator-driven — the InterruptEvent's source field must reflect
    that so transcripts don't mislead. Without the cause distinction
    the binder records every limit-driven exit as a user cancel.
    """
    sample = _make_active_sample()
    sample.tg = MagicMock()
    causes: list[str] = []
    sample.on_interrupt = lambda cause: causes.append(cause)
    err = LimitExceededError("token", value=100, limit=50)
    sample.limit_exceeded(err)
    assert causes == ["limit"]
    sample.tg.cancel_scope.cancel.assert_called_once_with()


def test_sample_interrupt_hook_failure_does_not_block_cancel() -> None:
    """A hook that raises must not prevent the task-group cancel.

    The hook is best-effort cleanup; cancel propagation is the
    primary contract of ``interrupt()`` and must always fire.
    """
    sample = _make_active_sample()
    sample.tg = MagicMock()

    def _bad(cause: str) -> None:
        raise RuntimeError("hook bug")

    sample.on_interrupt = _bad
    # Must not raise out of interrupt().
    sample.interrupt("score")
    sample.tg.cancel_scope.cancel.assert_called_once_with()


async def test_active_sample_exit_calls_on_complete_hook() -> None:
    """The ``active_sample`` context manager fires ``on_complete`` on exit.

    End-to-end pin: an ACP-aware binder registers itself via
    ``on_complete``; when the sample's full lifetime ends, the hook
    is fired exactly once with no arguments. Mirror of how
    ``LiveAcpTransport.finalize`` lands in production.
    """
    fired: list[str] = []

    async def _on_complete() -> None:
        fired.append("complete")

    async with active_sample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(id=1, input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        eval_id="eval-1",
    ) as active:
        active.on_complete = _on_complete
        assert fired == []
    assert fired == ["complete"]


async def test_active_sample_exit_on_complete_failure_is_logged_not_raised() -> None:
    """A failing ``on_complete`` hook is logged + swallowed.

    Sample teardown must never fail because of a binder's cleanup
    bug — the rest of the finally block (``active.complete()``, list
    removal, ContextVar reset) still has to run.
    """

    async def _bad() -> None:
        raise RuntimeError("finalize bug")

    # The active_sample context manager must exit cleanly even though
    # the hook raises. We rely on the warning-log path; we don't
    # assert on the log here because the pattern across this
    # codebase is to verify behavior, not the log message text.
    async with active_sample(
        task="t",
        log_location="mem://test",
        model="mockllm/model",
        sample=Sample(id=1, input="hi"),
        epoch=0,
        message_limit=None,
        token_limit=None,
        cost_limit=None,
        time_limit=None,
        working_limit=None,
        fails_on_error=False,
        transcript=Transcript(),
        eval_id="eval-1",
    ) as active:
        active.on_complete = _bad
    # Reaching here = teardown didn't raise. `active.completed` was
    # stamped despite the hook failure, proving the rest of the
    # finally block ran.
    assert active.completed is not None


async def test_limit_exceeded_records_interrupt_event_with_limit_source() -> None:
    """End-to-end: ``sample.limit_exceeded`` lands as ``source="limit"``.

    Pins the cause-propagation chain:
    ``ActiveSample.limit_exceeded`` → ``_fire_on_interrupt("limit")`` →
    registered ``on_interrupt`` (= ``LiveAcpTransport.cancel_current_turn``)
    → ``record_interrupt_event(source="limit")``. Regression: pre-fix,
    every limit hit was recorded as ``source="user_cancel"`` because
    the hook had no cause discriminator and ``cancel_current_turn``
    hardcoded the source.
    """
    from inspect_ai.event._interrupt import InterruptEvent
    from inspect_ai.log._transcript import init_transcript

    active = _make_active_sample()
    token = samples_var.set(active)
    # Install the sample's transcript on the current ContextVar so
    # the session's _TranscriptCapture.capture() picks it up (rather
    # than falling back to the shared default).
    init_transcript(active.transcript)
    try:
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            # Fake a task group so limit_exceeded can fire the cancel
            # scope without actually tearing anything down.
            active.tg = MagicMock()
            err = LimitExceededError("token", value=100, limit=50)
            active.limit_exceeded(err)
            # The InterruptEvent landed on the session's captured
            # transcript via the on_interrupt hook → cancel_current_turn.
            tr = acp._transcript_capture.transcript()
            interrupts = [e for e in tr.events if isinstance(e, InterruptEvent)]
            assert len(interrupts) == 1
            assert interrupts[0].source == "limit"
        await acp.finalize()
    finally:
        samples_var.reset(token)


async def test_user_cancel_via_interrupt_records_user_cancel_source() -> None:
    """Sibling test to the limit one: operator path stays ``source="user_cancel"``.

    Confirms the cause discriminator routes the two paths to different
    sources rather than blanket-overriding.
    """
    from inspect_ai.event._interrupt import InterruptEvent
    from inspect_ai.log._transcript import init_transcript

    active = _make_active_sample()
    token = samples_var.set(active)
    init_transcript(active.transcript)
    try:
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            active.tg = MagicMock()
            active.interrupt("score")
            tr = acp._transcript_capture.transcript()
            interrupts = [e for e in tr.events if isinstance(e, InterruptEvent)]
            assert len(interrupts) == 1
            assert interrupts[0].source == "user_cancel"
        await acp.finalize()
    finally:
        samples_var.reset(token)


async def test_limit_cancel_stamps_limit_sentinel_on_in_flight_model_event() -> None:
    """Per-event ``ModelEvent.error`` reflects ``cause="limit"`` not operator.

    Regression: pre-fix, ``cancel_current_turn(cause="limit")``
    snapshot path still stamped ``OPERATOR_CANCEL_ERROR`` on the
    in-flight ModelEvent (and "cancelled by user" on tool calls),
    leaving JSON logs and downstream renderers with conflicting
    provenance — the sample-level InterruptEvent.source said "limit"
    but the per-event stamps said "operator". This test pins the
    per-event sentinel matches the InterruptEvent source.
    """
    from inspect_ai.event._model import (
        LIMIT_CANCEL_ERROR,
        OPERATOR_CANCEL_ERROR,
        ModelEvent,
    )
    from inspect_ai.log._transcript import init_transcript
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    active = _make_active_sample()
    token = samples_var.set(active)
    init_transcript(active.transcript)
    try:
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            # Synthesise an in-flight ModelEvent so the snapshot path
            # has something to stamp. Mirrors what _model.py does at
            # generate() entry.
            ev = ModelEvent(
                model="m",
                input=[],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content("m", ""),
                pending=True,
            )
            acp._turn_cancel._active_model_event = ev
            active.tg = MagicMock()
            err = LimitExceededError("token", value=100, limit=50)
            active.limit_exceeded(err)
            # Per-event sentinel reflects the limit cause, not the
            # default operator marker.
            assert ev.error == LIMIT_CANCEL_ERROR
            assert ev.error != OPERATOR_CANCEL_ERROR
            assert ev.pending is None
        await acp.finalize()
    finally:
        samples_var.reset(token)


async def test_limit_cancel_stamps_limit_message_on_in_flight_tool_event() -> None:
    """Per-tool ``ToolCallError.message`` matches the limit cause."""
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import init_transcript

    active = _make_active_sample()
    token = samples_var.set(active)
    init_transcript(active.transcript)
    try:
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            tool_ev = ToolEvent(
                id="tc-1",
                function="bash",
                arguments={"cmd": "ls"},
                pending=True,
            )
            acp._turn_cancel._in_flight_tool_calls = ["tc-1"]
            acp._turn_cancel._in_flight_tool_events = {"tc-1": tool_ev}
            active.tg = MagicMock()
            err = LimitExceededError("token", value=100, limit=50)
            active.limit_exceeded(err)
            assert tool_ev.error is not None
            assert tool_ev.error.type == "cancelled"
            assert tool_ev.error.message == "Tool call cancelled by limit."
            assert tool_ev.failed is True
            assert tool_ev.pending is None
        await acp.finalize()
    finally:
        samples_var.reset(token)


async def test_user_cancel_stamps_operator_sentinel_on_in_flight_model_event() -> None:
    """Default ``cause="user_cancel"`` keeps the historical ``OPERATOR_CANCEL_ERROR`` stamp."""
    from inspect_ai.event._model import OPERATOR_CANCEL_ERROR, ModelEvent
    from inspect_ai.log._transcript import init_transcript
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import ModelOutput

    active = _make_active_sample()
    token = samples_var.set(active)
    init_transcript(active.transcript)
    try:
        async with acp_session() as acp:
            assert isinstance(acp, LiveAcpTransport)
            ev = ModelEvent(
                model="m",
                input=[],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput.from_content("m", ""),
                pending=True,
            )
            acp._turn_cancel._active_model_event = ev
            active.tg = MagicMock()
            active.interrupt("score")
            assert ev.error == OPERATOR_CANCEL_ERROR
            assert ev.pending is None
        await acp.finalize()
    finally:
        samples_var.reset(token)
