"""Phase 1 unit tests for ``AcpTransport`` types, factory, and accessors."""

import anyio
import pytest

from inspect_ai.agent._acp import AcpTransport, acp_session
from inspect_ai.agent._acp.transport import current_acp_transport


async def test_current_outside_scope_is_noop() -> None:
    acp = current_acp_transport()
    assert acp.session_id == "noop"


async def test_real_session_installed_inside_scope() -> None:
    async with acp_session() as acp:
        assert current_acp_transport() is acp
        assert acp.session_id != "noop"
        # session_id is stable across reads
        assert acp.session_id == acp.session_id


async def test_session_id_reset_after_scope_exits() -> None:
    async with acp_session():
        pass
    assert current_acp_transport().session_id == "noop"


async def test_nested_scope_is_noop_shadow() -> None:
    async with acp_session() as outer:
        assert outer.session_id != "noop"
        async with acp_session() as inner:
            assert inner.session_id == "noop"
            assert inner is not outer
            assert current_acp_transport() is inner
        # after inner exits, outer is restored
        assert current_acp_transport() is outer


async def test_triple_nested_scope_stays_noop_shadow() -> None:
    """Nested `acp_session()` calls install no-op shadows at ANY depth.

    Regression: an earlier implementation decided shadow-vs-live by
    inspecting the immediate parent's session shape via the
    ``_acp_var`` ContextVar alone. At depth 2 the parent was itself a
    NoOp shadow, so the predicate flipped back to "install Live" and
    silently produced a second real session — overwriting
    ``ActiveSample.acp_transport`` and double-registering the event
    router. The sticky ``_acp_live_active`` flag fixes this; depth 3+
    blocks see the upstream Live and shadow correctly.
    """
    async with acp_session() as level0:
        assert level0.session_id != "noop"
        async with acp_session() as level1:
            assert level1.session_id == "noop"
            async with acp_session() as level2:
                assert level2.session_id == "noop", (
                    "depth-2 acp_session() incorrectly installed a Live "
                    "session — sticky live-active flag is not in effect."
                )
                # All three are distinct instances.
                assert level0 is not level1
                assert level1 is not level2
                assert level0 is not level2
                assert current_acp_transport() is level2
            # After level2 exits, level1 (still a shadow) is restored.
            assert current_acp_transport() is level1
        # After level1 exits, level0 (the live one) is restored.
        assert current_acp_transport() is level0
    # After level0 exits, default singleton is restored.
    assert current_acp_transport().session_id == "noop"


async def test_publish_to_single_subscriber() -> None:
    async with acp_session() as acp:
        stream = acp.attach()
        acp.publish({"type": "agent_message_chunk", "content": "hello"})
        update = await stream.receive()
        assert update == {"type": "agent_message_chunk", "content": "hello"}


async def test_publish_fans_out_to_all_subscribers() -> None:
    async with acp_session() as acp:
        a = acp.attach()
        b = acp.attach()
        acp.publish({"k": "v"})
        assert await a.receive() == {"k": "v"}
        assert await b.receive() == {"k": "v"}


async def test_detach_closes_subscriber() -> None:
    async with acp_session() as acp:
        stream = acp.attach()
        acp.detach(stream)
        # Stream is closed; iterating it yields nothing.
        with pytest.raises(anyio.EndOfStream):
            await stream.receive()
        # Publishing after detach does not raise.
        acp.publish({"k": "v"})


async def test_publish_after_detach_is_safe_for_remaining_subscribers() -> None:
    async with acp_session() as acp:
        a = acp.attach()
        b = acp.attach()
        acp.detach(a)
        acp.publish({"k": "v"})
        assert await b.receive() == {"k": "v"}


async def test_subscriber_sees_eof_on_session_exit() -> None:
    async with acp_session() as acp:
        stream = acp.attach()
    # After the session exits, the stream should be at EOF.
    with pytest.raises(anyio.EndOfStream):
        await stream.receive()


async def test_noop_attach_returns_closed_stream() -> None:
    acp = current_acp_transport()
    assert acp.session_id == "noop"
    stream = acp.attach()
    with pytest.raises(anyio.EndOfStream):
        await stream.receive()


async def test_noop_publish_and_detach_are_safe() -> None:
    acp = current_acp_transport()
    stream = acp.attach()
    acp.publish({"k": "v"})  # no subscribers; no error
    acp.detach(stream)  # no-op


async def test_concurrent_tasks_have_isolated_sessions() -> None:
    """Sibling tasks each see their own session under genuine overlap.

    Two tasks each open their own ``acp_session()`` and keep both
    scopes open simultaneously. ``current_acp_transport()`` must return
    *each task's own* session — proving ContextVar isolation under
    genuine overlap, not just sequential entry.
    """
    results: dict[str, str] = {}
    a_entered = anyio.Event()
    b_entered = anyio.Event()

    async def task(label: str, my_event: anyio.Event, peer_event: anyio.Event) -> None:
        async with acp_session() as acp:
            results[f"{label}_id"] = acp.session_id
            my_event.set()
            # Wait until the peer has also entered before reading
            # current_acp_transport() — guarantees both scopes overlap.
            await peer_event.wait()
            results[f"{label}_current"] = current_acp_transport().session_id

    async with anyio.create_task_group() as tg:
        tg.start_soon(task, "a", a_entered, b_entered)
        tg.start_soon(task, "b", b_entered, a_entered)

    assert results["a_id"] != "noop"
    assert results["b_id"] != "noop"
    assert results["a_id"] != results["b_id"]
    assert results["a_current"] == results["a_id"]
    assert results["b_current"] == results["b_id"]


async def test_publish_prunes_subscriber_whose_receive_was_closed() -> None:
    async with acp_session() as acp:
        a = acp.attach()
        b = acp.attach()
        await a.aclose()  # client-side disconnect
        acp.publish({"k": "v"})
        # Live subscriber still received the update.
        assert await b.receive() == {"k": "v"}
        # Dead subscriber was pruned: a second publish only iterates the
        # remaining live subscriber, so a third publish + receive on b
        # works as normal.
        acp.publish({"k": "v2"})
        assert await b.receive() == {"k": "v2"}
        # Internal check: only one subscriber remains.
        assert len(acp._subscribers) == 1  # type: ignore[attr-defined]


async def test_subscriber_buffer_is_unbounded(monkeypatch) -> None:
    """Verifies the buffer never drops events even under burst load.

    Matches the hooks-system contract — dropped ACP updates would
    surface as missing transcript chunks / tool-call rows in client
    UIs. We accept the (bounded-by-event-rate) memory cost in
    exchange for lossless delivery.
    """
    warnings: list[str] = []

    def capture(msg: str, *_args: object, **_kwargs: object) -> None:
        warnings.append(msg)

    from inspect_ai.agent._acp import transport_live as live_module

    monkeypatch.setattr(live_module.logger, "warning", capture)

    burst = 10_000
    async with acp_session() as acp:
        receive = acp.attach()  # subscribe but never drain
        for i in range(burst):
            acp.publish({"i": i})

        # No drops, no warnings.
        assert warnings == []

        # Buffer holds every event, in order.
        drained: list[dict[str, int]] = []
        for _ in range(burst):
            drained.append(receive.receive_nowait())
        assert drained == [{"i": i} for i in range(burst)]


async def test_acp_session_satisfies_protocol() -> None:
    async with acp_session() as acp:
        assert isinstance(acp, AcpTransport)
    assert isinstance(current_acp_transport(), AcpTransport)


# ---------------------------------------------------------------------------
# Multi-client prompt coordination (interrupt_pending + subscribers)
#
# Only the in-proc TUI has modal prompt state, so the subscribers are
# the in-process hook the TUI uses to auto-enter / auto-exit prompt
# mode regardless of who triggered the cancel. Tests pin the state
# machine: cancel sets pending and fires interrupted; submit clears
# pending and fires prompt_resolved; submit without a prior cancel
# does NOT fire prompt_resolved. Also covers subscriber-error
# robustness (one broken subscriber doesn't block others) and the
# no-op session's pass-through behavior.
# ---------------------------------------------------------------------------


from inspect_ai.model._chat_message import ChatMessageUser  # noqa: E402


async def test_interrupt_pending_starts_false() -> None:
    async with acp_session() as acp:
        assert acp.interrupt_pending is False


async def test_cancel_sets_interrupt_pending_and_fires_interrupted() -> None:
    """``cancel_current_turn`` flips the pending flag + fires interrupted hook."""
    async with acp_session() as acp:
        fires: list[None] = []
        acp.subscribe_interrupted(lambda: fires.append(None))
        acp.cancel_current_turn()
        assert acp.interrupt_pending is True
        assert len(fires) == 1


async def test_submit_after_cancel_clears_pending_and_fires_resolved() -> None:
    """``submit_user_message`` after a cancel clears pending + fires resolved hook."""
    async with acp_session() as acp:
        resolved: list[None] = []
        acp.subscribe_prompt_resolved(lambda: resolved.append(None))
        acp.cancel_current_turn()
        assert acp.interrupt_pending is True
        acp.submit_user_message(ChatMessageUser(content="resume"))
        assert acp.interrupt_pending is False
        assert len(resolved) == 1


async def test_submit_without_cancel_does_not_fire_resolved() -> None:
    """A plain ``submit_user_message`` (no preceding cancel) must NOT fire resolved.

    Pinned because the in-proc TUI's auto-exit hook would otherwise
    dismiss prompt mode on every queued user message, including
    ordinary turn-starting messages — making the modal flicker out
    of existence.
    """
    async with acp_session() as acp:
        resolved: list[None] = []
        acp.subscribe_prompt_resolved(lambda: resolved.append(None))
        acp.submit_user_message(ChatMessageUser(content="hello"))
        assert acp.interrupt_pending is False
        assert resolved == []


async def test_multiple_subscribers_all_fire() -> None:
    async with acp_session() as acp:
        interrupted_calls: list[str] = []
        resolved_calls: list[str] = []
        acp.subscribe_interrupted(lambda: interrupted_calls.append("a"))
        acp.subscribe_interrupted(lambda: interrupted_calls.append("b"))
        acp.subscribe_prompt_resolved(lambda: resolved_calls.append("a"))
        acp.subscribe_prompt_resolved(lambda: resolved_calls.append("b"))
        acp.cancel_current_turn()
        acp.submit_user_message(ChatMessageUser(content="ok"))
        assert sorted(interrupted_calls) == ["a", "b"]
        assert sorted(resolved_calls) == ["a", "b"]


async def test_unsubscribe_stops_firing() -> None:
    async with acp_session() as acp:
        fires: list[None] = []
        unsub = acp.subscribe_interrupted(lambda: fires.append(None))
        acp.cancel_current_turn()
        assert len(fires) == 1
        # Reset for next cycle.
        acp.submit_user_message(ChatMessageUser(content="ok"))
        unsub()
        acp.cancel_current_turn()
        # Subscriber removed; count unchanged.
        assert len(fires) == 1


async def test_unsubscribe_is_idempotent() -> None:
    """Double-unsubscribe is safe (no exception) — supports cleanup races."""
    async with acp_session() as acp:
        unsub = acp.subscribe_prompt_resolved(lambda: None)
        unsub()
        unsub()  # should not raise


async def test_broken_subscriber_does_not_block_others() -> None:
    """One subscriber raising must not prevent siblings from firing.

    Mirrors the resilience contract on
    ``Transcript._subscribe`` — the producer's task continues
    even if a downstream listener is broken.
    """

    def broken() -> None:
        raise RuntimeError("boom")

    async with acp_session() as acp:
        good_calls: list[None] = []
        acp.subscribe_interrupted(broken)
        acp.subscribe_interrupted(lambda: good_calls.append(None))
        acp.cancel_current_turn()
        assert len(good_calls) == 1


async def test_noop_session_subscribe_returns_noop_unsubscribe() -> None:
    """No-op session accepts subscribe + returns a no-op unsubscribe.

    Lets callers use a uniform subscribe/unsubscribe pattern without
    isinstance-guarding the session type.
    """
    from inspect_ai.agent._acp.transport_noop import NoOpAcpTransport

    noop = NoOpAcpTransport()
    unsub_i = noop.subscribe_interrupted(lambda: None)
    unsub_r = noop.subscribe_prompt_resolved(lambda: None)
    assert noop.interrupt_pending is False
    # Should not raise.
    unsub_i()
    unsub_r()


async def test_after_cancel_drain_clears_pending_via_channel_observer() -> None:
    """``interrupt_pending`` clears when the channel drains a pre-queued message.

    Regression: in the submit-then-cancel-then-drain sequence, the operator
    queued a follow-up BEFORE pressing Esc. The cancel sets pending=True.
    The agent's ``after_cancel`` drains the queued message — but the channel
    is ACP-agnostic and won't directly notify the transport. The transport
    subscribes to ``channel.subscribe_drained`` during ``maybe_bind`` so it
    can flip pending=False when its queued :class:`UserMessage` reaches
    the consumer. Without this hook the TUI's modal-prompt UI sticks open
    even after the redirect was applied.
    """
    from inspect_ai.agent._channel import agent_channel
    from inspect_ai.model._chat_message import ChatMessageUser as _U

    async with acp_session() as acp:
        # Open a channel + manually bind it to the transport. In normal
        # use the agent_channel() factory does this via sample_active(),
        # but these unit tests run outside any sample context — wire the
        # binding directly so submit/cancel/drain all route through the
        # bound ref.
        async with agent_channel() as ch:
            assert acp.maybe_bind(ch, ch._ref()) is True
            resolved: list[None] = []
            acp.subscribe_prompt_resolved(lambda: resolved.append(None))
            # Order: submit FIRST, then cancel. submit doesn't fire resolved
            # (no pending yet); cancel sets pending.
            acp.submit_user_message(_U(content="resume"))
            assert acp.interrupt_pending is False
            assert resolved == []
            acp.cancel_current_turn()
            assert acp.interrupt_pending is True
            # Agent loop runs after_cancel — drains the queued message,
            # which fires the subscribe_drained observer on the transport,
            # which calls resolve_if_pending().
            drained = await ch.after_cancel(messages=[])
            assert any(isinstance(m, _U) for m in drained)
            assert acp.interrupt_pending is False
            assert len(resolved) == 1


async def test_after_cancel_drain_no_double_fire_when_submit_already_cleared() -> None:
    """The drain observer must not re-fire resolved when submit already did.

    The common ordering — cancel first, then user submits, then drain —
    already clears pending in :meth:`submit_user_message`. The subsequent
    channel drain fires the observer, which calls resolve_if_pending on
    a non-pending state (no-op). The resolved subscriber must NOT fire
    twice (would cause the TUI to attempt a redundant exit).
    """
    from inspect_ai.agent._channel import agent_channel
    from inspect_ai.model._chat_message import ChatMessageUser as _U

    async with acp_session() as acp:
        async with agent_channel() as ch:
            assert acp.maybe_bind(ch, ch._ref()) is True
            resolved: list[None] = []
            acp.subscribe_prompt_resolved(lambda: resolved.append(None))
            acp.cancel_current_turn()
            # Submit BEFORE drain — clears pending + fires resolved.
            acp.submit_user_message(_U(content="ok"))
            assert acp.interrupt_pending is False
            assert len(resolved) == 1
            # Drain via after_cancel — observer fires but pending already
            # cleared, so no second resolve.
            await ch.after_cancel(messages=[])
            assert len(resolved) == 1


async def test_repeated_cancel_keeps_pending_and_re_fires_interrupted() -> None:
    """Cancel-cancel (without intervening submit) re-fires + keeps pending.

    A second Interrupt click while already-pending shouldn't silently
    swallow the cancel — the InterruptEvent is still recorded and
    subscribers still fire. Pinned because the in-proc TUI guards
    against this via its own UI but the session layer doesn't (and
    shouldn't — that's a UI concern).
    """
    async with acp_session() as acp:
        fires: list[None] = []
        acp.subscribe_interrupted(lambda: fires.append(None))
        acp.cancel_current_turn()
        acp.cancel_current_turn()
        assert acp.interrupt_pending is True
        assert len(fires) == 2


# ---------------------------------------------------------------------------
# Phase 14: approver-client registry on LiveAcpTransport
#
# Tracks ACP clients that can handle ``session/request_permission``.
# The configured ``human_approver`` checks this registry at prompt
# time and routes through ACP when at least one is attached, falling
# back to the in-proc panel / console flow when none are.
# ---------------------------------------------------------------------------


class _StubApproverClient:
    """Minimal ApproverClient — just needed for registry assertions."""

    async def request_permission(self, request):
        raise NotImplementedError  # not exercised in registry tests

    async def drain_notifications(self) -> None:
        """No-op — registry tests don't exercise the drain barrier."""


def _bind_approver(acp, client):
    """Attach + promote-to-ready as the connection handler would.

    Mirrors the two-step ``attach_approver_client`` (pending) +
    ``notify_approver_attach(client)`` (ready) sequence the
    connection handler runs across the replay await. Returns the
    unsubscribe from ``attach_approver_client``.
    """
    unsub = acp.attach_approver_client(client)
    acp.notify_approver_attach(client)
    return unsub


async def test_approver_clients_starts_empty() -> None:
    async with acp_session() as acp:
        assert acp.has_approver_clients() is False
        assert acp.approver_driver_chain() == []


async def test_attach_approver_client_flips_predicate_and_unsubscribe_reverts() -> None:
    """One attach+notify → True; calling the returned unsubscribe → False."""
    async with acp_session() as acp:
        client = _StubApproverClient()
        unsub = _bind_approver(acp, client)
        assert acp.has_approver_clients() is True
        assert acp.approver_driver_chain() == [client]
        unsub()
        assert acp.has_approver_clients() is False
        assert acp.approver_driver_chain() == []


async def test_attach_multiple_clients_independent_unsubscribe() -> None:
    """N clients attach independently; per-client unsubscribe removes only its entry."""
    async with acp_session() as acp:
        client_a = _StubApproverClient()
        client_b = _StubApproverClient()
        unsub_a = _bind_approver(acp, client_a)
        unsub_b = _bind_approver(acp, client_b)
        # Notify alone doesn't promote — driver_chain falls back to
        # first-attached order. (In production the connection handler
        # also calls mark_active right before notify; that promotion
        # is tested separately.)
        assert acp.approver_driver_chain() == [client_a, client_b]
        unsub_a()
        assert acp.approver_driver_chain() == [client_b]
        unsub_b()
        assert acp.approver_driver_chain() == []


async def test_approver_driver_chain_returns_snapshot_copy() -> None:
    """``approver_driver_chain()`` returns a copy — mutating it doesn't affect the registry.

    Pinned because the approval shim iterates the returned list
    while the connection can attach/detach concurrently. A live
    reference would race.
    """
    async with acp_session() as acp:
        client = _StubApproverClient()
        _bind_approver(acp, client)
        snapshot = acp.approver_driver_chain()
        snapshot.clear()
        assert acp.approver_driver_chain() == [client]  # registry unchanged


async def test_mark_active_promotes_client_to_head_of_chain() -> None:
    """``mark_active`` makes ``client`` the driver; chain is [driver, ...rest_in_attach_order]."""
    async with acp_session() as acp:
        a = _StubApproverClient()
        b = _StubApproverClient()
        c = _StubApproverClient()
        # Attach + notify each, but explicitly reset _last_active to
        # None to test the no-prompt-yet fallback. (In production,
        # notify_approver_attach is called after mark_active in the
        # bind path, but here we want the explicit first-attached
        # fallback behavior.)
        for client in (a, b, c):
            acp.attach_approver_client(client)
            acp.notify_approver_attach(client)
        # Reset driver to test the explicit mark_active calls below.
        acp.mark_active_session_client(_StubApproverClient())  # unknown → no-op
        # Mark middle client active — it moves to head; others keep
        # attach order (a, c).
        acp.mark_active_session_client(b)
        assert acp.approver_driver_chain() == [b, a, c]
        # Mark another active — it moves to head; b drops to attach order.
        acp.mark_active_session_client(c)
        assert acp.approver_driver_chain() == [c, a, b]


async def test_mark_active_ignores_unknown_client() -> None:
    """``mark_active`` with a non-registered client silently no-ops.

    Defensive against the detach-before-prompt race: a client could
    detach between the prompt arriving and ``mark_active`` firing.
    """
    async with acp_session() as acp:
        a = _StubApproverClient()
        rogue = _StubApproverClient()
        _bind_approver(acp, a)
        acp.mark_active_session_client(rogue)  # no-op
        # Driver chain unchanged.
        assert acp.approver_driver_chain() == [a]


async def test_unsubscribing_the_active_driver_resets_to_first_attached() -> None:
    """If the active driver detaches, the chain falls back to first-attached order."""
    async with acp_session() as acp:
        a = _StubApproverClient()
        b = _StubApproverClient()
        _bind_approver(acp, a)
        unsub_b = _bind_approver(acp, b)
        acp.mark_active_session_client(b)
        assert acp.approver_driver_chain() == [b, a]
        unsub_b()
        # b is gone — fall back to first-attached.
        assert acp.approver_driver_chain() == [a]


async def test_session_exit_clears_approver_clients() -> None:
    """``__aexit__`` drops registrations so late callbacks can't fire into a closed connection."""
    fake_session = None
    async with acp_session() as acp:
        _bind_approver(acp, _StubApproverClient())
        assert acp.has_approver_clients() is True
        fake_session = acp
    # Outside the context manager, the session is closed.
    assert fake_session.has_approver_clients() is False
    assert fake_session.approver_driver_chain() == []


async def test_attach_unsubscribe_is_idempotent() -> None:
    """Double-unsubscribe is safe (no exception) — supports cleanup races."""
    async with acp_session() as acp:
        unsub = acp.attach_approver_client(_StubApproverClient())
        unsub()
        unsub()  # should not raise


async def test_noop_session_approver_client_is_no_op() -> None:
    """No-op session: predicate False, attach returns no-op unsubscribe, chain empty."""
    from inspect_ai.agent._acp.transport_noop import NoOpAcpTransport

    noop = NoOpAcpTransport()
    client = _StubApproverClient()
    assert noop.has_approver_clients() is False
    assert noop.has_ever_had_approver_client() is False
    assert noop.approver_driver_chain() == []
    unsub = noop.attach_approver_client(client)
    # Still False — the no-op session doesn't actually register.
    assert noop.has_approver_clients() is False
    assert noop.has_ever_had_approver_client() is False
    # mark_active and notify_approver_attach on no-op are also safe.
    noop.mark_active_session_client(client)
    noop.notify_approver_attach(client)
    unsub()  # no-op, no raise
    # subscribe_approver_attach on no-op returns a no-op unsubscribe.
    cb_unsub = noop.subscribe_approver_attach(lambda: None)
    cb_unsub()  # no-op, no raise


async def test_has_ever_had_approver_client_starts_false() -> None:
    """Bare session: no client has ever attached → predicate is False."""
    async with acp_session() as acp:
        assert acp.has_ever_had_approver_client() is False


async def test_has_ever_had_approver_client_flips_true_on_attach() -> None:
    """attach_approver_client flips the one-way bit (even before notify).

    Pinned because this is the signal the approval shim uses to
    distinguish "no operator ever connected" (panel fallback OK)
    from "operator was here, dropped mid-approval" (must park).
    The bit must flip on registration (NOT on notify) so a parked
    approval shim that loses its client mid-bind still knows ACP
    routing was intended.
    """
    async with acp_session() as acp:
        client = _StubApproverClient()
        unsub = acp.attach_approver_client(client)
        # Bit flips on pending attach, even before notify.
        assert acp.has_ever_had_approver_client() is True
        # But the client isn't yet routable.
        assert acp.has_approver_clients() is False
        unsub()
        # One-way: detach does NOT reset the flag.
        assert acp.has_ever_had_approver_client() is True
        assert acp.has_approver_clients() is False


async def test_attach_alone_hides_client_from_driver_chain() -> None:
    """Pending (attached-but-not-notified) clients are invisible to dispatch.

    Pinned regression of the half-bound visibility race the
    reviewer flagged: ``Forwarders.start`` registers the approver
    BEFORE the replay await. If the registry exposed the new
    client in ``driver_chain`` at that point, a concurrent
    approval shim could dispatch into the half-bound connection
    before replay shows the operator the conversation context.
    The fix routes pending clients through ``_pending_clients`` —
    invisible to ``driver_chain`` until ``notify_approver_attach``
    promotes them.
    """
    async with acp_session() as acp:
        client = _StubApproverClient()
        acp.attach_approver_client(client)
        # Pending: ``has_ever_had`` is True (operator intent recorded),
        # but ``has_approver_clients`` / ``driver_chain`` are empty.
        assert acp.has_ever_had_approver_client() is True
        assert acp.has_approver_clients() is False
        assert acp.approver_driver_chain() == []
        # notify_approver_attach promotes to ready.
        acp.notify_approver_attach(client)
        assert acp.has_approver_clients() is True
        assert acp.approver_driver_chain() == [client]


async def test_attach_alone_does_not_fire_subscribers() -> None:
    """``attach_approver_client`` is a registration-only step.

    Companion to the half-bound visibility fix: subscribers ALSO
    must not fire on registration. If they did, a parked approval
    shim could wake and snapshot the driver chain — finding it
    empty (good) but then re-parking with a fresh subscription
    that races the upcoming ``notify_approver_attach``. Decoupling
    means the bind is fully atomic from the shim's perspective:
    one wake-up, one consistent snapshot.
    """
    async with acp_session() as acp:
        fires = 0

        def _on_attach() -> None:
            nonlocal fires
            fires += 1

        acp.subscribe_approver_attach(_on_attach)
        acp.attach_approver_client(_StubApproverClient())
        # Registration alone does NOT fire — the bind isn't ready yet.
        assert fires == 0


async def test_notify_approver_attach_promotes_and_fires() -> None:
    """``notify_approver_attach(client)`` promotes pending → ready and fires subscribers."""
    async with acp_session() as acp:
        fires = 0

        def _on_attach() -> None:
            nonlocal fires
            fires += 1

        unsub_cb = acp.subscribe_approver_attach(_on_attach)
        client = _StubApproverClient()
        acp.attach_approver_client(client)
        assert fires == 0
        assert acp.approver_driver_chain() == []  # pending, invisible
        acp.notify_approver_attach(client)
        assert fires == 1
        assert acp.approver_driver_chain() == [client]  # promoted
        # Spurious re-notify on an already-ready client is safe —
        # client stays in ``_clients`` (no duplicate), subscribers
        # fire again (the approval shim's event re-arm dedupes).
        acp.notify_approver_attach(client)
        assert fires == 2
        assert acp.approver_driver_chain() == [client]
        unsub_cb()
        acp.notify_approver_attach(client)
        assert fires == 2  # unsubscribed


async def test_notify_approver_attach_does_not_fabricate_after_unsub() -> None:
    """Notify after unsub does NOT re-add the client to ready.

    Pinned regression of a fabrication bug: if ``Forwarders.start``
    aborts replay and runs ``stop()`` (which unsubscribes), but
    ``_post_bind_setup_locked`` still calls
    ``notify_approver_attach(self)`` afterward — an unconditional
    promote would re-insert the cleaned-up handler into
    ``_clients`` with no unsubscribe left to remove it. The shim
    would then dispatch into a dead connection forever. The fix
    gates promotion on the client being currently pending.
    """
    async with acp_session() as acp:
        client = _StubApproverClient()
        unsub = acp.attach_approver_client(client)
        unsub()  # simulate teardown between attach and notify
        # Subscribers should still fire (spurious wake is harmless),
        # but the client must NOT reappear in ready.
        fires = 0

        def _on_attach() -> None:
            nonlocal fires
            fires += 1

        acp.subscribe_approver_attach(_on_attach)
        acp.notify_approver_attach(client)
        assert fires == 1
        assert acp.approver_driver_chain() == []
        assert acp.has_approver_clients() is False


async def test_notify_approver_attach_for_specific_pending_client_only() -> None:
    """Only the named client is promoted; sibling pending clients stay pending.

    Pinned because the two-connection-concurrent-bind scenario
    requires per-client notify: if connection A finishes binding
    while connection B is still mid-replay, A's notify must NOT
    accidentally promote B (whose replay isn't done yet). Each
    bind sequence notifies for its own client.
    """
    async with acp_session() as acp:
        a = _StubApproverClient()
        b = _StubApproverClient()
        acp.attach_approver_client(a)
        acp.attach_approver_client(b)
        # Both pending, neither visible.
        assert acp.approver_driver_chain() == []
        # Promote A only.
        acp.notify_approver_attach(a)
        assert acp.approver_driver_chain() == [a]
        # B still pending.
        # Now promote B.
        acp.notify_approver_attach(b)
        assert acp.approver_driver_chain() == [a, b]


async def test_subscribe_approver_attach_unsubscribe_is_idempotent() -> None:
    """Double-unsubscribe of an attach callback is safe."""
    async with acp_session() as acp:
        unsub = acp.subscribe_approver_attach(lambda: None)
        unsub()
        unsub()  # no raise


# ---------------------------------------------------------------------------
# AgentChannel.is_live wiring — only flipped when an ACP server is accepting
# ---------------------------------------------------------------------------


async def test_maybe_bind_marks_channel_live_when_server_accepting(
    monkeypatch,
) -> None:
    """Channel flips live when the server is accepting at bind time.

    Unbind then clears the marker.
    """
    from inspect_ai.agent._acp import server as server_module
    from inspect_ai.agent._channel import agent_channel

    monkeypatch.setattr(server_module, "acp_server_accepting_clients", lambda: True)
    async with acp_session() as acp:
        async with agent_channel() as ch:
            ref = ch._ref()
            assert acp.maybe_bind(ch, ref) is True
            assert ch.is_live is True
            acp.unbind(ref)
            assert ch.is_live is False


async def test_maybe_bind_leaves_channel_inert_when_server_not_accepting(
    monkeypatch,
) -> None:
    """Channel stays inert when no server is accepting at bind time.

    LiveAcpTransport is installed per-sample regardless of ``--acp-server``
    (for in-proc / sub-agent reachability), but ``is_live`` must stay
    False so consumers don't accidentally enable interactive plumbing
    on non-server-enabled evals.
    """
    from inspect_ai.agent._acp import server as server_module
    from inspect_ai.agent._channel import agent_channel

    monkeypatch.setattr(server_module, "acp_server_accepting_clients", lambda: False)
    async with acp_session() as acp:
        async with agent_channel() as ch:
            ref = ch._ref()
            assert acp.maybe_bind(ch, ref) is True
            assert ch.is_live is False
            # subscribe_drained still happened — the bind succeeded —
            # only mark_live was gated.
            acp.unbind(ref)
            assert ch.is_live is False  # idempotent on the unset case
