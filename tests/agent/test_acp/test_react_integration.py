"""Phase 4 end-to-end tests for ACP integration with `react()`."""

from typing import Any, cast

import anyio

from inspect_ai.agent import react
from inspect_ai.agent._acp import AcpSession
from inspect_ai.agent._acp._session import _LiveAcpSession
from inspect_ai.agent._agent import AgentState
from inspect_ai.event import InterruptEvent
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.tool import Tool, ToolCall, tool

from ._capture import capture_session_tool, slow_tool_with_event


def _user_state(text: str = "start") -> AgentState:
    return AgentState(messages=[ChatMessageUser(content=text)])


async def test_react_runs_unchanged_with_no_acp_producer() -> None:
    """react() works as before when no producer is interacting with it."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        model = get_model(
            "mockllm/model",
            memoize=False,
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "42"},
                ),
            ],
        )
        agent = react(model=model)
        result = await agent(_user_state())
        assert "42" in result.output.completion
    finally:
        _transcript.reset(token)


async def test_track_model_event_populates_session_during_generate() -> None:
    """While a generate is in flight, session._active_model_event is set."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        observed_during_generate: list[Any] = []

        async def slow_done(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            await anyio.sleep(0.3)
            return ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            )

        # Sequence: turn 1 → capture tool; turn 2 → slow generate that submits.
        outputs: list[Any] = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="capture_session",
                tool_arguments={},
            ),
            slow_done,
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            item = next(outputs_iter)
            if callable(item):
                return item(input, tools, tc, cfg)
            return item

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[capture_session_tool(captured, ready)], model=model)

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                await agent(_user_state())

            async def observer() -> None:
                await ready.wait()
                # Capture tool fired; the next generate (slow_done) is about
                # to start. Wait for it to enter, then peek the session.
                await anyio.sleep(0.05)
                live = cast(_LiveAcpSession, captured["acp"])
                observed_during_generate.append(live._active_model_event)

            tg.start_soon(run_agent)
            tg.start_soon(observer)

        assert len(observed_during_generate) == 1
        active = observed_during_generate[0]
        assert active is not None
        assert active.uuid is not None
    finally:
        _transcript.reset(token)


async def test_track_tool_call_populates_session_during_tool_execution() -> None:
    """While a tool is in flight, session._in_flight_tool_calls contains its id."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()
        observed_in_flight: list[list[str]] = []

        # mockllm outputs: turn 1 → capture; turn 2 → slow tool; turn 3 → done.
        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call("mockllm/model", "capture_session", {})
            elif call_count[0] == 2:
                return ModelOutput.for_tool_call(
                    "mockllm/model", "slow_tool", {}, tool_call_id="slow-id-1"
                )
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "done"}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        agent = react(
            tools=[
                capture_session_tool(captured, ready),
                slow_tool_with_event(release),
            ],
            model=model,
        )

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                await agent(_user_state())

            async def observer() -> None:
                await ready.wait()
                # Capture happened on turn 1. Now wait long enough for turn 2's
                # slow_tool to enter the track_tool_call scope.
                await anyio.sleep(0.1)
                live = cast(_LiveAcpSession, captured["acp"])
                observed_in_flight.append(list(live._in_flight_tool_calls))
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(observer)

        assert observed_in_flight == [["slow-id-1"]]
    finally:
        _transcript.reset(token)


async def test_cancel_mid_generate() -> None:
    """Producer cancels during a slow generate.

    react recovers with the queued follow-up message and completes via a later mockllm output.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()

        async def slow_generate(
            input: Any, tools: Any, tc: Any, cfg: Any
        ) -> ModelOutput:
            await anyio.sleep(5)  # cancel target
            return ModelOutput.from_content("mockllm/model", "never reached")

        outputs: list[Any] = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="capture_session",
                tool_arguments={},
            ),
            slow_generate,  # cancel hits this
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "ok after cancel"},
            ),
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            item = next(outputs_iter)
            if callable(item):
                return item(input, tools, tc, cfg)
            return item

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[capture_session_tool(captured, ready)], model=model)

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                result = await agent(_user_state())
                assert "ok after cancel" in result.output.completion

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.1)  # let slow_generate begin
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="follow-up"))
                acp.cancel_current_turn()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        # The follow-up user message should appear in the transcript.
        follow_ups = [
            m
            for m in transcript.events
            if hasattr(m, "event") and getattr(m, "event", None) == "interrupt"
        ]
        assert len(follow_ups) == 1
    finally:
        _transcript.reset(token)


async def test_cancel_mid_tool_call() -> None:
    """Producer cancels during a slow tool.

    react gets a synthetic repair message + the queued follow-up, then completes.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()

        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call("mockllm/model", "capture_session", {})
            elif call_count[0] == 2:
                return ModelOutput.for_tool_call(
                    "mockllm/model", "slow_tool", {}, tool_call_id="slow-id-2"
                )
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "recovered"}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        agent = react(
            tools=[
                capture_session_tool(captured, ready),
                slow_tool_with_event(release),
            ],
            model=model,
        )

        final_state: list[AgentState] = []

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                result = await agent(_user_state())
                final_state.append(result)

            async def producer() -> None:
                await ready.wait()
                # Wait for slow_tool to enter; then cancel.
                await anyio.sleep(0.15)
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="please stop"))
                acp.cancel_current_turn()
                # Release in case the tool is still running (it should be
                # cancelled, but unblock for safety).
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        assert len(final_state) == 1
        result = final_state[0]
        assert "recovered" in result.output.completion

        # A synthetic ChatMessageTool with type="cancelled" should appear.
        repair_messages = [
            m
            for m in result.messages
            if isinstance(m, ChatMessageTool)
            and m.error is not None
            and m.error.type == "cancelled"
        ]
        assert len(repair_messages) >= 1
        # The queued user message should also appear.
        operator_messages = [
            m
            for m in result.messages
            if isinstance(m, ChatMessageUser) and m.source == "operator"
        ]
        assert any(m.content == "please stop" for m in operator_messages)
    finally:
        _transcript.reset(token)


async def test_interrupt_event_recorded_with_correct_fields() -> None:
    """A cancel-mid-generate emits an InterruptEvent with the right fields."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()

        async def slow_generate(
            input: Any, tools: Any, tc: Any, cfg: Any
        ) -> ModelOutput:
            await anyio.sleep(5)
            return ModelOutput.from_content("mockllm/model", "never")

        outputs: list[Any] = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="capture_session",
                tool_arguments={},
            ),
            slow_generate,
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "ok"},
            ),
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            item = next(outputs_iter)
            if callable(item):
                return item(input, tools, tc, cfg)
            return item

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[capture_session_tool(captured, ready)], model=model)

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                await agent(_user_state())

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.1)
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="next"))
                acp.cancel_current_turn()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        events = [e for e in transcript.events if isinstance(e, InterruptEvent)]
        assert len(events) == 1
        ev = events[0]
        assert ev.source == "user_cancel"
        assert ev.interrupted == "generate"
        assert ev.interrupted_model_event_id is not None
        assert ev.interrupted_tool_call_id is None
    finally:
        _transcript.reset(token)


async def test_inject_between_turns() -> None:
    """Operator message submitted between turns is picked up on the next."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()

        call_count = [0]

        def gen_callable(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="capture_session",
                    tool_arguments={},
                )
            return ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "saw operator"},
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen_callable)
        agent = react(tools=[capture_session_tool(captured, ready)], model=model)

        final_state: list[AgentState] = []

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                result = await agent(_user_state())
                final_state.append(result)

            async def producer() -> None:
                await ready.wait()
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="interjection"))

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        assert len(final_state) == 1
        # The interjection should be present in state.messages with
        # source="operator" (normalized by Phase 3).
        operator_msgs = [
            m
            for m in final_state[0].messages
            if isinstance(m, ChatMessageUser) and m.source == "operator"
        ]
        assert any(m.content == "interjection" for m in operator_msgs)
    finally:
        _transcript.reset(token)


async def test_react_no_submit_cancel_mid_tool() -> None:
    """`react_no_submit()` honors the same splice."""
    from inspect_ai.agent._react import react_no_submit

    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()

        # react_no_submit doesn't loop forever — it exits on no-tool-calls if
        # there's no on_continue hook. Sequence: capture tool → slow tool →
        # (cancel) → on_continue brings us back → final content (no tools) → exit.
        outputs = iter(
            [
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="capture_session",
                    tool_arguments={},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="slow_tool",
                    tool_arguments={},
                    tool_call_id="rns-1",
                ),
                ModelOutput.from_content("mockllm/model", "all done"),
            ]
        )
        model = get_model("mockllm/model", memoize=False, custom_outputs=outputs)

        # Build react_no_submit via the same factory path react() uses.
        agent = react_no_submit(
            name=None,
            description=None,
            prompt=None,
            tools=[
                capture_session_tool(captured, ready),
                slow_tool_with_event(release),
            ],
            model=model,
            on_continue=None,
            retry_refusals=None,
            compaction=None,
            truncation="disabled",
            approval=None,
        )

        final_state: list[AgentState] = []

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                result = await agent(_user_state())
                final_state.append(result)

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.15)
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="stop"))
                acp.cancel_current_turn()
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        assert len(final_state) == 1
        result = final_state[0]
        # Final completion is the "all done" content output.
        assert "all done" in (result.output.completion or "")
        # Operator message should appear in state.
        operator_msgs = [
            m
            for m in result.messages
            if isinstance(m, ChatMessageUser) and m.source == "operator"
        ]
        assert any(m.content == "stop" for m in operator_msgs)
    finally:
        _transcript.reset(token)


async def test_cancel_repairs_all_unanswered_tool_calls_in_batch() -> None:
    """Cancel during multi-tool batch: every unanswered call gets a repair.

    Sequential tool execution means a cancel during call_2 leaves call_1
    completed-but-lost (its result never returned from
    ``_execute_tools_impl``). The session should synthesize repair
    messages for *both* call_1 and call_2 so the model on the next turn
    sees matched tool_call/result pairs.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()

        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call("mockllm/model", "capture_session", {})
            elif call_count[0] == 2:
                # Two tool calls in a single assistant message. Sequential
                # execution: tool_1 runs first (immediately returns), then
                # tool_2 (slow). Cancel hits during tool_2.
                msg = ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="batch-1",
                            function="fast_tool",
                            arguments={},
                        ),
                        ToolCall(
                            id="batch-2",
                            function="slow_tool",
                            arguments={},
                        ),
                    ],
                )
                output = ModelOutput(
                    model="mockllm/model",
                    choices=[
                        ChatCompletionChoice(message=msg, stop_reason="tool_calls")
                    ],
                )
                return output
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "recovered"}
            )

        @tool
        def fast_tool() -> Tool:
            async def execute() -> str:
                """A tool that returns immediately."""
                return "fast done"

            return execute

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        agent = react(
            tools=[
                capture_session_tool(captured, ready),
                fast_tool(),
                slow_tool_with_event(release),
            ],
            model=model,
        )

        final_state: list[AgentState] = []

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                result = await agent(_user_state())
                final_state.append(result)

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.25)  # wait for tool batch to start tool_2
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="halt"))
                acp.cancel_current_turn()
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        assert len(final_state) == 1
        result = final_state[0]

        # Both batch-1 and batch-2 must have ChatMessageTool entries in
        # state.messages — otherwise the model would see an assistant
        # message with two tool_calls but only one result, which most
        # providers reject.
        tool_results = [
            m
            for m in result.messages
            if isinstance(m, ChatMessageTool)
            and m.tool_call_id in ("batch-1", "batch-2")
        ]
        assert {m.tool_call_id for m in tool_results} == {"batch-1", "batch-2"}
        # At least one is a synthetic "cancelled" repair.
        cancelled = [m for m in tool_results if m.error and m.error.type == "cancelled"]
        assert len(cancelled) >= 1
    finally:
        _transcript.reset(token)


async def test_cancel_clears_pending_on_in_flight_events() -> None:
    """Cancelled ModelEvent and ToolEvent must not be left ``pending=True``.

    Anyio cancellation propagates through the model/tool execution code
    without running the normal completion paths that clear ``pending``.
    :meth:`cancel_current_turn` clears the flag directly so the
    transcript / log viewer doesn't show the cancelled rows as forever
    in-flight.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()

        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call("mockllm/model", "capture_session", {})
            elif call_count[0] == 2:
                return ModelOutput.for_tool_call(
                    "mockllm/model", "slow_tool", {}, tool_call_id="pending-1"
                )
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "done"}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        agent = react(
            tools=[
                capture_session_tool(captured, ready),
                slow_tool_with_event(release),
            ],
            model=model,
        )

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                await agent(_user_state())

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.15)  # let slow_tool enter
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="stop"))
                acp.cancel_current_turn()
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        # No tool event for pending-1 should be left pending=True.
        from inspect_ai.event import ToolEvent

        pending_tool_events = [
            e
            for e in transcript.events
            if isinstance(e, ToolEvent) and e.id == "pending-1" and e.pending
        ]
        assert pending_tool_events == [], (
            f"slow_tool event was left pending: {pending_tool_events}"
        )
    finally:
        _transcript.reset(token)


async def test_cancel_notifies_event_updated_for_cancelled_events() -> None:
    """Cancel must call `transcript()._event_updated` on cleared events.

    Mutating ``pending = None`` updates the in-memory list trivially
    (same object reference) but downstream subscribers — log writers,
    hooks — register via ``Transcript._event_updated``. Normal
    completion paths in ``_model.py`` and ``_call_tools.py`` always
    pair the flag clear with the update notification; the cancel path
    must do the same or buffered consumers retain the original pending
    event and never see the cancellation.
    """
    transcript = Transcript()
    update_calls: list[Any] = []

    original_update = transcript._event_updated

    def spy_update(event: Any) -> None:
        update_calls.append(event)
        original_update(event)

    transcript._event_updated = spy_update  # type: ignore[method-assign]

    token = _transcript.set(transcript)
    try:
        captured: dict[str, AcpSession] = {}
        ready = anyio.Event()
        release = anyio.Event()

        call_count = [0]

        def gen(input: Any, tools: Any, tc: Any, cfg: Any) -> ModelOutput:
            call_count[0] += 1
            if call_count[0] == 1:
                return ModelOutput.for_tool_call("mockllm/model", "capture_session", {})
            elif call_count[0] == 2:
                return ModelOutput.for_tool_call(
                    "mockllm/model", "slow_tool", {}, tool_call_id="notify-1"
                )
            return ModelOutput.for_tool_call(
                "mockllm/model", "submit", {"answer": "done"}
            )

        model = get_model("mockllm/model", memoize=False, custom_outputs=gen)
        agent = react(
            tools=[
                capture_session_tool(captured, ready),
                slow_tool_with_event(release),
            ],
            model=model,
        )

        async with anyio.create_task_group() as tg:

            async def run_agent() -> None:
                await agent(_user_state())

            async def producer() -> None:
                await ready.wait()
                await anyio.sleep(0.15)
                acp = captured["acp"]
                acp.submit_user_message(ChatMessageUser(content="stop"))
                acp.cancel_current_turn()
                release.set()

            tg.start_soon(run_agent)
            tg.start_soon(producer)

        # The cancelled ToolEvent for notify-1 must have triggered
        # _event_updated so log/hook subscribers see the cleared state.
        from inspect_ai.event import ToolEvent

        cancelled_tool_updates = [
            e for e in update_calls if isinstance(e, ToolEvent) and e.id == "notify-1"
        ]
        assert cancelled_tool_updates, (
            "_event_updated was not called for the cancelled ToolEvent; "
            "log writers / hooks would not see the cleared pending flag"
        )
    finally:
        _transcript.reset(token)
