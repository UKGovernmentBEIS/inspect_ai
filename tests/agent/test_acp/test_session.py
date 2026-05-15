"""Phase 1 unit tests for ``AcpSession`` types, factory, and accessors."""

import anyio
import pytest

from inspect_ai.agent import AcpSession, acp_session
from inspect_ai.agent._acp import _session as session_module
from inspect_ai.agent._acp._session import current_acp_session


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

    monkeypatch.setattr(session_module.logger, "warning", capture)

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
