"""Phase 1 unit tests for ``AcpSession`` types, factory, and accessors."""

import anyio
import pytest

from inspect_ai.agent import AcpSession, acp_session
from inspect_ai.agent._acp.session import current_acp_session


async def test_current_outside_scope_is_noop() -> None:
    acp = current_acp_session()
    assert acp.session_id == "noop"


async def test_real_session_installed_inside_scope() -> None:
    async with acp_session() as acp:
        assert current_acp_session() is acp
        assert acp.session_id != "noop"
        # session_id is stable across reads
        assert acp.session_id == acp.session_id


async def test_session_id_reset_after_scope_exits() -> None:
    async with acp_session():
        pass
    assert current_acp_session().session_id == "noop"


async def test_nested_scope_is_noop_shadow() -> None:
    async with acp_session() as outer:
        assert outer.session_id != "noop"
        async with acp_session() as inner:
            assert inner.session_id == "noop"
            assert inner is not outer
            assert current_acp_session() is inner
        # after inner exits, outer is restored
        assert current_acp_session() is outer


async def test_triple_nested_scope_stays_noop_shadow() -> None:
    """Nested `acp_session()` calls install no-op shadows at ANY depth.

    Regression: an earlier implementation decided shadow-vs-live by
    inspecting the immediate parent's session shape via the
    ``_acp_var`` ContextVar alone. At depth 2 the parent was itself a
    NoOp shadow, so the predicate flipped back to "install Live" and
    silently produced a second real session — overwriting
    ``ActiveSample.acp_session`` and double-registering the event
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
                assert current_acp_session() is level2
            # After level2 exits, level1 (still a shadow) is restored.
            assert current_acp_session() is level1
        # After level1 exits, level0 (the live one) is restored.
        assert current_acp_session() is level0
    # After level0 exits, default singleton is restored.
    assert current_acp_session().session_id == "noop"


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
    acp = current_acp_session()
    assert acp.session_id == "noop"
    stream = acp.attach()
    with pytest.raises(anyio.EndOfStream):
        await stream.receive()


async def test_noop_publish_and_detach_are_safe() -> None:
    acp = current_acp_session()
    stream = acp.attach()
    acp.publish({"k": "v"})  # no subscribers; no error
    acp.detach(stream)  # no-op


async def test_concurrent_tasks_have_isolated_sessions() -> None:
    """Sibling tasks each see their own session under genuine overlap.

    Two tasks each open their own ``acp_session()`` and keep both
    scopes open simultaneously. ``current_acp_session()`` must return
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
            # current_acp_session() — guarantees both scopes overlap.
            await peer_event.wait()
            results[f"{label}_current"] = current_acp_session().session_id

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

    from inspect_ai.agent._acp import session_live as live_module

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
        assert isinstance(acp, AcpSession)
    assert isinstance(current_acp_session(), AcpSession)


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
    ``Transcript._add_subscriber`` — the producer's task continues
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
    from inspect_ai.agent._acp.session_noop import NoOpAcpSession

    noop = NoOpAcpSession()
    unsub_i = noop.subscribe_interrupted(lambda: None)
    unsub_r = noop.subscribe_prompt_resolved(lambda: None)
    assert noop.interrupt_pending is False
    # Should not raise.
    unsub_i()
    unsub_r()


async def test_after_cancel_clears_pending_when_draining_prequeued_message() -> None:
    """When ``after_cancel`` drains a message that was queued BEFORE the cancel.

    Submit-then-cancel never goes through ``submit_user_message`` again,
    so ``_interrupt_pending`` would stay True forever without
    ``after_cancel`` clearing it. Late subscribers (TUI re-attach after
    sample switch) would see stale pending state. Pinned to keep the
    state machine consistent across both orderings of submit/cancel.
    """
    async with acp_session() as acp:
        resolved: list[None] = []
        acp.subscribe_prompt_resolved(lambda: resolved.append(None))
        # Order: submit FIRST, then cancel. submit doesn't fire resolved
        # (no pending yet); cancel sets pending.
        acp.submit_user_message(ChatMessageUser(content="resume"))
        assert acp.interrupt_pending is False
        assert resolved == []
        acp.cancel_current_turn()
        assert acp.interrupt_pending is True
        # Agent loop runs after_cancel — drains the queued message.
        # Should clear pending and fire resolved.
        drained = await acp.after_cancel(messages=[])
        # Drained contents include the pre-queued user message.
        assert any(isinstance(m, ChatMessageUser) for m in drained)
        assert acp.interrupt_pending is False
        assert len(resolved) == 1


async def test_after_cancel_no_double_fire_when_submit_already_cleared() -> None:
    """``after_cancel`` must NOT fire resolved again when submit already did.

    The common ordering — cancel first, then user submits, then
    after_cancel drains — already cleared pending in
    submit_user_message. after_cancel sees pending=False and shouldn't
    re-fire (would cause the TUI to attempt a redundant exit).
    """
    async with acp_session() as acp:
        resolved: list[None] = []
        acp.subscribe_prompt_resolved(lambda: resolved.append(None))
        acp.cancel_current_turn()
        # Submit BEFORE after_cancel — clears pending + fires.
        acp.submit_user_message(ChatMessageUser(content="ok"))
        assert acp.interrupt_pending is False
        assert len(resolved) == 1
        await acp.after_cancel(messages=[])
        # No second fire.
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
# Phase 14: approver-client registry on LiveAcpSession
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


async def test_approver_clients_starts_empty() -> None:
    async with acp_session() as acp:
        assert acp.has_approver_clients() is False
        assert acp.approver_driver_chain() == []


async def test_attach_approver_client_flips_predicate_and_unsubscribe_reverts() -> None:
    """One attach → True; calling the returned unsubscribe → False."""
    async with acp_session() as acp:
        client = _StubApproverClient()
        unsub = acp.attach_approver_client(client)
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
        unsub_a = acp.attach_approver_client(client_a)
        unsub_b = acp.attach_approver_client(client_b)
        # No prompt has been sent yet → driver chain is attach order.
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
        acp.attach_approver_client(client)
        snapshot = acp.approver_driver_chain()
        snapshot.clear()
        assert acp.approver_driver_chain() == [client]  # registry unchanged


async def test_mark_active_promotes_client_to_head_of_chain() -> None:
    """``mark_active`` makes ``client`` the driver; chain is [driver, ...rest_in_attach_order]."""
    async with acp_session() as acp:
        a = _StubApproverClient()
        b = _StubApproverClient()
        c = _StubApproverClient()
        acp.attach_approver_client(a)
        acp.attach_approver_client(b)
        acp.attach_approver_client(c)
        # No prompt yet — first-attached is the fallback driver.
        assert acp.approver_driver_chain() == [a, b, c]
        # Mark middle client active — it moves to head; others keep
        # attach order (a, c).
        acp.mark_active_approver_client(b)
        assert acp.approver_driver_chain() == [b, a, c]
        # Mark another active — it moves to head; b drops to attach order.
        acp.mark_active_approver_client(c)
        assert acp.approver_driver_chain() == [c, a, b]


async def test_mark_active_ignores_unknown_client() -> None:
    """``mark_active`` with a non-registered client silently no-ops.

    Defensive against the detach-before-prompt race: a client could
    detach between the prompt arriving and ``mark_active`` firing.
    """
    async with acp_session() as acp:
        a = _StubApproverClient()
        rogue = _StubApproverClient()
        acp.attach_approver_client(a)
        acp.mark_active_approver_client(rogue)  # no-op
        # Driver chain unchanged.
        assert acp.approver_driver_chain() == [a]


async def test_unsubscribing_the_active_driver_resets_to_first_attached() -> None:
    """If the active driver detaches, the chain falls back to first-attached order."""
    async with acp_session() as acp:
        a = _StubApproverClient()
        b = _StubApproverClient()
        acp.attach_approver_client(a)
        unsub_b = acp.attach_approver_client(b)
        acp.mark_active_approver_client(b)
        assert acp.approver_driver_chain() == [b, a]
        unsub_b()
        # b is gone — fall back to first-attached.
        assert acp.approver_driver_chain() == [a]


async def test_session_exit_clears_approver_clients() -> None:
    """``__aexit__`` drops registrations so late callbacks can't fire into a closed connection."""
    fake_session = None
    async with acp_session() as acp:
        acp.attach_approver_client(_StubApproverClient())
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
    from inspect_ai.agent._acp.session_noop import NoOpAcpSession

    noop = NoOpAcpSession()
    assert noop.has_approver_clients() is False
    assert noop.approver_driver_chain() == []
    unsub = noop.attach_approver_client(_StubApproverClient())
    # Still False — the no-op session doesn't actually register.
    assert noop.has_approver_clients() is False
    # mark_active on no-op is also safe.
    noop.mark_active_approver_client(_StubApproverClient())
    unsub()  # no-op, no raise
