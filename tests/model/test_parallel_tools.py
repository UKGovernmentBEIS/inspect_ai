"""Tests for parallel tool execution in execute_tools.

The execute_tools loop partitions an assistant message's tool_calls into
ordered stages: consecutive `parallel=True` calls coalesce into one
concurrent stage, while each `parallel=False` call is a one-element stage
that acts as a barrier preserving the model's declared call ordering.
"""

import anyio
import pytest

from inspect_ai.event._tool import ToolEvent
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool import ToolError, tool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_def import ToolDef

# -- helpers ----------------------------------------------------------------


def call(function: str, call_id: str, **arguments: object) -> ToolCall:
    return ToolCall(
        id=call_id, function=function, arguments=arguments, parse_error=None
    )


def assistant(*calls: ToolCall) -> ChatMessageAssistant:
    return ChatMessageAssistant(content=[], tool_calls=list(calls))


# -- tool fixtures ----------------------------------------------------------
# These need to be module-level @tool definitions so the registry recognizes
# them; their `parallel` declaration is what we're exercising.


@tool(parallel=True)
def parallel_echo():
    async def parallel_echo(label: str) -> str:
        """Return the label after yielding once.

        Args:
            label: The label to echo back.
        """
        await anyio.sleep(0)
        return label

    return parallel_echo


@tool
def serial_echo():
    async def serial_echo(label: str) -> str:
        """Return the label.

        Args:
            label: The label to echo back.
        """
        return label

    return serial_echo


@tool(parallel=True)
def parallel_raise_tool_error():
    async def parallel_raise_tool_error(message: str) -> str:
        """Raise a ToolError so siblings can continue.

        Args:
            message: Error message.
        """
        raise ToolError(message)

    return parallel_raise_tool_error


@tool(parallel=True)
def parallel_raise_exception():
    async def parallel_raise_exception(message: str) -> str:
        """Raise an unhandled exception that should cancel siblings.

        Args:
            message: Error message.
        """
        raise RuntimeError(message)

    return parallel_raise_exception


# -- tests ------------------------------------------------------------------


async def test_parallel_default_is_serial():
    """A bare @tool defaults to parallel=False (opt-in semantics)."""
    tdef = ToolDef(serial_echo())
    assert tdef.parallel is False


async def test_parallel_true_opt_in():
    """@tool(parallel=True) opts in."""
    tdef = ToolDef(parallel_echo())
    assert tdef.parallel is True


async def test_serial_batch_preserves_order():
    """All-serial batch returns ChatMessageTool messages in tool_call order."""
    tdef = ToolDef(serial_echo())
    calls = [call("serial_echo", f"c{i}", label=f"L{i}") for i in range(3)]
    messages, _ = await execute_tools([assistant(*calls)], [tdef])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    assert [m.tool_call_id for m in tool_msgs] == ["c0", "c1", "c2"]
    assert [m.content for m in tool_msgs] == ["L0", "L1", "L2"]


async def test_parallel_batch_runs_concurrently():
    """A stage of parallel-safe calls actually executes concurrently.

    Verified by a barrier-like rendezvous: each tool waits for a shared
    Event that only fires once N tools have arrived. If execution were
    serial the second tool would never start, leaving the first blocked
    forever (test would time out via anyio's fail_after).
    """
    arrivals = [0]
    all_arrived = anyio.Event()
    total = 3

    @tool(parallel=True)
    def rendezvous():
        async def rendezvous(label: str) -> str:
            """Synchronize with siblings before returning.

            Args:
                label: The label to echo back.
            """
            arrivals[0] += 1
            if arrivals[0] == total:
                all_arrived.set()
            await all_arrived.wait()
            return label

        return rendezvous

    tdef = ToolDef(rendezvous())
    calls = [call("rendezvous", f"c{i}", label=f"L{i}") for i in range(total)]

    with anyio.fail_after(5):
        messages, _ = await execute_tools([assistant(*calls)], [tdef])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    assert [m.tool_call_id for m in tool_msgs] == ["c0", "c1", "c2"]
    assert [m.content for m in tool_msgs] == ["L0", "L1", "L2"]


async def test_mixed_batch_serial_acts_as_barrier():
    """[par, par, ser, par] runs as {0,1} concurrently, then {2}, then {3}.

    The serial call must observe results of any prior parallel calls but
    must complete before subsequent parallel calls begin.
    """
    sequence: list[str] = []

    @tool(parallel=True)
    def par():
        async def par(label: str) -> str:
            """Record entry and exit timestamps via the sequence list.

            Args:
                label: The label to record.
            """
            sequence.append(f"start:{label}")
            await anyio.sleep(0.01)
            sequence.append(f"end:{label}")
            return label

        return par

    @tool
    def ser():
        async def ser(label: str) -> str:
            """Record entry and exit timestamps.

            Args:
                label: The label to record.
            """
            sequence.append(f"start:{label}")
            await anyio.sleep(0.01)
            sequence.append(f"end:{label}")
            return label

        return ser

    par_def = ToolDef(par())
    ser_def = ToolDef(ser())

    calls = [
        call("par", "c0", label="A"),
        call("par", "c1", label="B"),
        call("ser", "c2", label="C"),
        call("par", "c3", label="D"),
    ]
    messages, _ = await execute_tools([assistant(*calls)], [par_def, ser_def])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    assert [m.tool_call_id for m in tool_msgs] == ["c0", "c1", "c2", "c3"]

    # A and B must both start before either ends (concurrent stage).
    a_start, b_start = sequence.index("start:A"), sequence.index("start:B")
    a_end, b_end = sequence.index("end:A"), sequence.index("end:B")
    assert max(a_start, b_start) < min(a_end, b_end)

    # C (serial) starts only after both A and B end.
    c_start = sequence.index("start:C")
    assert c_start > max(a_end, b_end)

    # D (parallel) starts only after C ends.
    c_end = sequence.index("end:C")
    d_start = sequence.index("start:D")
    assert d_start > c_end


async def test_tool_error_in_parallel_does_not_abort_siblings():
    """ToolError becomes tool-result content; sibling completes normally."""
    err_def = ToolDef(parallel_raise_tool_error())
    ok_def = ToolDef(parallel_echo())

    calls = [
        call("parallel_raise_tool_error", "c0", message="boom"),
        call("parallel_echo", "c1", label="survived"),
    ]
    messages, _ = await execute_tools([assistant(*calls)], [err_def, ok_def])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].error is not None and tool_msgs[0].error.type == "unknown"
    assert tool_msgs[0].error.message == "boom"
    assert tool_msgs[1].error is None
    assert tool_msgs[1].content == "survived"


async def test_unhandled_exception_in_parallel_cancels_siblings_and_raises():
    """An unhandled exception aborts the stage and propagates."""
    started_b = anyio.Event()
    cancelled_b = [False]

    @tool(parallel=True)
    def slow_b():
        async def slow_b() -> str:
            """Sleep long enough to be cancelled by the sibling's failure."""
            started_b.set()
            try:
                await anyio.sleep(10)
            except BaseException:
                cancelled_b[0] = True
                raise
            return "should-not-return"

        return slow_b

    @tool(parallel=True)
    def fast_fail():
        async def fast_fail() -> str:
            """Wait for the sibling to be running, then raise."""
            await started_b.wait()
            raise RuntimeError("kaboom")

        return fast_fail

    a = ToolDef(fast_fail())
    b = ToolDef(slow_b())

    # Unique ids so we can find this stage's events in the shared transcript.
    sibling_id = "ex-cancel-sibling-c0"
    failer_id = "ex-cancel-failer-c1"
    calls = [
        call("slow_b", sibling_id),
        call("fast_fail", failer_id),
    ]
    with pytest.raises(RuntimeError, match="kaboom"):
        await execute_tools([assistant(*calls)], [a, b])

    assert cancelled_b[0], "Sibling slow_b should have been cancelled"

    # Events for the stage are updated before the exception propagates, so the
    # cancelled sibling's ToolEvent should be in the transcript with the
    # "cancelled" error type — NOT "timeout", and not blamed on the operator.
    from inspect_ai.log._transcript import transcript

    sibling_event = next(
        e
        for e in transcript().events
        if isinstance(e, ToolEvent) and e.id == sibling_id and not e.pending
    )
    assert sibling_event.error is not None
    assert sibling_event.error.type == "cancelled"
    assert "operator" not in sibling_event.error.message
    assert "timeout" not in sibling_event.error.message.lower()
    assert "sibling" in sibling_event.error.message.lower()


async def test_per_call_cancel_isolates_to_one_call():
    """event._cancel() on one call only cancels that call; siblings finish.

    Drives the cancel through a ToolEvent we hook via a custom tool that
    grabs the event reference as soon as it is set up. We rely on the
    `_set_cancel_fn` plumbing in `_execute_tools_impl`.
    """
    # We need a way to capture each call's ToolEvent and selectively cancel
    # one of them while letting the others complete. The cleanest way to
    # do this from inside a tool is to read the active transcript's last
    # ToolEvents, find the one we want, and call _cancel() on it. We use
    # a shared coordination event to ensure the cancel happens after both
    # tools are in-flight.
    from inspect_ai.log._transcript import transcript

    both_started = anyio.Event()
    started_count = [0]
    cancel_fired = anyio.Event()

    @tool(parallel=True)
    def waiter():
        async def waiter(label: str) -> str:
            """Wait until the test cancels us or releases us.

            Args:
                label: The label.
            """
            started_count[0] += 1
            if started_count[0] == 2:
                both_started.set()

            if label == "target":
                # Find our own ToolEvent by id in the transcript and cancel
                # it from the outside via a separate task.
                await both_started.wait()
                # Locate ourselves in the transcript pending events.
                events = transcript().events
                me = next(
                    (
                        e
                        for e in reversed(events)
                        if isinstance(e, ToolEvent)
                        and e.function == "waiter"
                        and e.pending
                        and e.arguments.get("label") == "target"
                    ),
                    None,
                )
                assert me is not None
                me._cancel()
                cancel_fired.set()
                # Sleep so the cancellation has time to fire while we're awaiting.
                await anyio.sleep(5)
                return "should-not-reach"
            else:
                await both_started.wait()
                await cancel_fired.wait()
                # Give the cancellation a moment to propagate before we return.
                await anyio.sleep(0.05)
                return label

        return waiter

    tdef = ToolDef(waiter())
    calls = [
        call("waiter", "c0", label="target"),
        call("waiter", "c1", label="survivor"),
    ]

    with anyio.fail_after(5):
        messages, _ = await execute_tools([assistant(*calls)], [tdef])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    by_id = {m.tool_call_id: m for m in tool_msgs}

    # Target was cancelled — synthesized cancellation message with timeout error.
    assert by_id["c0"].error is not None
    assert by_id["c0"].error.type == "timeout"
    # Survivor completed normally.
    assert by_id["c1"].error is None
    assert by_id["c1"].content == "survivor"


async def test_message_id_associates_to_each_calls_chat_message_tool():
    """Each ToolEvent's message_id points at its corresponding ChatMessageTool."""
    from inspect_ai.log._transcript import transcript

    tdef = ToolDef(parallel_echo())
    # Unique call ids to avoid colliding with the global transcript shared
    # across tests in this module.
    expected_ids = {f"msgid-c{i}" for i in range(3)}
    calls = [call("parallel_echo", f"msgid-c{i}", label=f"L{i}") for i in range(3)]
    messages, _ = await execute_tools([assistant(*calls)], [tdef])

    tool_msgs = [m for m in messages if isinstance(m, ChatMessageTool)]
    msg_by_call_id = {m.tool_call_id: m for m in tool_msgs}

    completed = [
        e
        for e in transcript().events
        if isinstance(e, ToolEvent) and e.id in expected_ids and not e.pending
    ]
    assert len(completed) == 3

    for ev in completed:
        expected = msg_by_call_id[ev.id]
        assert ev.message_id == expected.id, (
            f"event {ev.id} should reference message {expected.id}, got {ev.message_id}"
        )


async def test_fast_tool_completes_before_slow_sibling_finishes():
    """Each parallel tool's ToolEvent is finalised when *that* call finishes.

    Regression: previously we finalised every event in the post-stage loop,
    so a fast 10ms tool would inherit the slow sibling's elapsed time on
    its `completed` timestamp and `working_time`.
    """
    from inspect_ai.log._transcript import transcript

    @tool(parallel=True)
    def sleeper():
        async def sleeper(label: str, ms: int) -> str:
            """Sleep for `ms` milliseconds, then return label.

            Args:
                label: Label to return.
                ms: Milliseconds to sleep.
            """
            await anyio.sleep(ms / 1000.0)
            return label

        return sleeper

    tdef = ToolDef(sleeper())
    fast_id = "timing-fast"
    slow_id = "timing-slow"
    calls = [
        call("sleeper", fast_id, label="fast", ms=10),
        call("sleeper", slow_id, label="slow", ms=300),
    ]
    await execute_tools([assistant(*calls)], [tdef])

    events_by_id = {
        e.id: e
        for e in transcript().events
        if isinstance(e, ToolEvent) and e.id in {fast_id, slow_id} and not e.pending
    }
    fast_ev = events_by_id[fast_id]
    slow_ev = events_by_id[slow_id]

    assert fast_ev.completed is not None
    assert slow_ev.completed is not None
    # The fast event must finalise well before the slow one. The construction
    # gap is ~290ms; allow generous slack for CI jitter.
    gap = (slow_ev.completed - fast_ev.completed).total_seconds()
    assert gap > 0.1, f"fast event should finalise long before slow; gap was {gap:.3f}s"

    # Per-event working_time should reflect each call's own elapsed time,
    # not the stage's. With the bug, the fast tool would inherit the
    # slow tool's ~300ms; fixed, it should be a fraction of the slow one.
    assert fast_ev.working_time is not None
    assert slow_ev.working_time is not None
    assert fast_ev.working_time < slow_ev.working_time / 2, (
        f"fast working_time {fast_ev.working_time:.3f}s should be far less "
        f"than slow {slow_ev.working_time:.3f}s"
    )


async def test_operator_cancel_finalises_when_cancel_hits_not_stage_end():
    """A cancelled fast call finalises at cancel time, not when slow sibling finishes.

    Regression: operator cancellation used to defer event finalisation to
    the post-stage loop, so a cancelled fast call inherited the slow
    sibling's elapsed time on its `completed`/`working_time`.
    """
    from inspect_ai.log._transcript import transcript

    both_started = anyio.Event()
    started = [0]

    @tool(parallel=True)
    def cancellable():
        async def cancellable(label: str) -> str:
            """Wait then return label, or be cancelled before then.

            Args:
                label: The label.
            """
            started[0] += 1
            if started[0] == 2:
                both_started.set()

            if label == "target":
                # Wait for sibling to also be running, then cancel ourselves.
                await both_started.wait()
                events = transcript().events
                me = next(
                    e
                    for e in reversed(events)
                    if isinstance(e, ToolEvent)
                    and e.function == "cancellable"
                    and e.pending
                    and e.arguments.get("label") == "target"
                )
                me._cancel()
                await anyio.sleep(5)
                return "unreachable"
            else:
                # Sibling sleeps long enough that the gap between
                # cancel-time and stage-end is unambiguous.
                await both_started.wait()
                await anyio.sleep(0.3)
                return label

        return cancellable

    tdef = ToolDef(cancellable())
    target_id = "op-cancel-target"
    survivor_id = "op-cancel-survivor"
    calls = [
        call("cancellable", target_id, label="target"),
        call("cancellable", survivor_id, label="survivor"),
    ]

    with anyio.fail_after(5):
        await execute_tools([assistant(*calls)], [tdef])

    events_by_id = {
        e.id: e
        for e in transcript().events
        if isinstance(e, ToolEvent)
        and e.id in {target_id, survivor_id}
        and not e.pending
    }
    target_ev = events_by_id[target_id]
    survivor_ev = events_by_id[survivor_id]

    # Target was cancelled — preserves pre-existing serial semantics:
    # "timeout" error type, failed=None (only sibling-cancel sets failed=True).
    assert target_ev.error is not None
    assert target_ev.error.type == "timeout"
    assert target_ev.failed is None, (
        f"operator-cancel should preserve failed=None, got {target_ev.failed!r}"
    )

    # Target's `completed` must come well before survivor's. With the bug,
    # both would land within microseconds of each other at stage end.
    assert target_ev.completed is not None
    assert survivor_ev.completed is not None
    gap = (survivor_ev.completed - target_ev.completed).total_seconds()
    assert gap > 0.1, (
        f"cancelled target should finalise before survivor; gap was {gap:.3f}s"
    )

    # And target's working_time should reflect when the cancel hit, not
    # the survivor's elapsed time.
    assert target_ev.working_time is not None
    assert survivor_ev.working_time is not None
    assert target_ev.working_time < survivor_ev.working_time / 2, (
        f"target working_time {target_ev.working_time:.3f}s should be far "
        f"less than survivor {survivor_ev.working_time:.3f}s"
    )
