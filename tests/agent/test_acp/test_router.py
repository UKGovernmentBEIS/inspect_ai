"""Phase 6 tests for the in-process ACP event router.

Two test styles:

- **Unit**: direct router exercise with synthetic events; ``session.publish``
  monkey-patched to a list collector.
- **Integration**: drive ``react()`` against mockllm under ``acp_session()``
  with a live subscriber stream, using the Phase 4 capture-via-tool pattern.
"""

from typing import Any, cast

import anyio
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ContentChunk,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent import react
from inspect_ai.agent._acp import acp_session
from inspect_ai.agent._acp._router import _AcpEventRouter, _tool_call_status
from inspect_ai.agent._acp._session import _LiveAcpSession
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._as_tool import as_tool
from inspect_ai.event import (
    CompactionEvent,
    Event,
    InfoEvent,
    InterruptEvent,
    LoggerEvent,
    SampleInitEvent,
    SampleLimitEvent,
    SpanBeginEvent,
    SpanEndEvent,
    StateEvent,
    StoreEvent,
    SubtaskEvent,
    ToolEvent,
)
from inspect_ai.event._logger import LoggingMessage
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
)
from inspect_ai.tool._tool import Tool, tool

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _new_session() -> _LiveAcpSession:
    return _LiveAcpSession()


def _attach_router(
    session: _LiveAcpSession,
) -> tuple[_AcpEventRouter, list[SessionNotification]]:
    """Build a router and route its publications into a list collector."""
    published: list[SessionNotification] = []
    session.publish = published.append  # type: ignore[method-assign,assignment]
    router = _AcpEventRouter(session)
    router.attach()
    return router, published


def _model_event(
    *,
    text: str | None = None,
    reasoning: str | None = None,
    blocks: list[Any] | None = None,
    pending: bool | None = None,
    empty_output: bool = False,
) -> ModelEvent:
    """Build a synthetic ModelEvent with controlled output."""
    if empty_output:
        output = ModelOutput(model="mockllm/model", choices=[])
    else:
        if blocks is None:
            blocks_built: list[Any] = []
            if reasoning is not None:
                blocks_built.append(ContentReasoning(reasoning=reasoning))
            if text is not None:
                blocks_built.append(ContentText(text=text))
            blocks = blocks_built
        message = ChatMessageAssistant(content=blocks if blocks else "")
        output = ModelOutput(
            model="mockllm/model",
            choices=[ChatCompletionChoice(message=message)],
        )
    event = ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=output,
        pending=pending,
    )
    return event


def _tool_event(
    *,
    tool_id: str = "tc1",
    function: str = "my_tool",
    pending: bool | None = None,
    error: bool = False,
) -> ToolEvent:
    from inspect_ai.tool._tool_call import ToolCallError

    event = ToolEvent(
        id=tool_id,
        function=function,
        arguments={},
        pending=pending,
        error=ToolCallError(type="unknown", message="boom") if error else None,
    )
    return event


def _span_begin(span_id: str, *, span_type: str | None = "agent") -> SpanBeginEvent:
    return SpanBeginEvent(id=span_id, name="span", type=span_type)


def _span_end(span_id: str) -> SpanEndEvent:
    return SpanEndEvent(id=span_id)


def _chunk_text(chunk: ContentChunk) -> str:
    """Pull the text out of a content chunk that carries a TextContentBlock."""
    assert isinstance(chunk.content, TextContentBlock)
    return chunk.content.text


# ---------------------------------------------------------------------------
# Router unit tests — depth tracking, filter, detach, errors
# ---------------------------------------------------------------------------


def test_depth_counter_increments_and_decrements_on_agent_spans() -> None:
    """SpanBegin(type=agent) increments depth; matching SpanEnd decrements."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)
        assert router._sub_agent_depth == 0
        tr._event(_span_begin("a"))
        assert router._sub_agent_depth == 1
        tr._event(_span_begin("b"))
        assert router._sub_agent_depth == 2
        tr._event(_span_end("b"))
        assert router._sub_agent_depth == 1
        tr._event(_span_end("a"))
        assert router._sub_agent_depth == 0
    finally:
        _transcript.reset(token)


def test_depth_counter_ignores_non_agent_spans() -> None:
    """Spans of other types (tool, handoff, None) do not move the counter."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)
        tr._event(_span_begin("t", span_type="tool"))
        tr._event(_span_begin("h", span_type="handoff"))
        tr._event(_span_begin("n", span_type=None))
        assert router._sub_agent_depth == 0
    finally:
        _transcript.reset(token)


def test_sub_agent_filter_drops_events_at_depth_one() -> None:
    """Events emitted while a sub-agent boundary is open do not publish."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_span_begin("inner"))
        tr._event(_model_event(text="hidden"))
        tr._event(_span_end("inner"))
        assert published == []
    finally:
        _transcript.reset(token)


def test_unknown_span_end_does_not_underflow() -> None:
    """A SpanEnd with an id we never saw must not decrement the counter."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)
        tr._event(_span_end("never-began"))
        assert router._sub_agent_depth == 0
    finally:
        _transcript.reset(token)


def test_detach_removes_the_subscription() -> None:
    """After detach(), subsequent events are not delivered to the router."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, published = _attach_router(session)
        tr._event(_model_event(text="before"))
        assert len(published) == 1
        router.detach()
        tr._event(_model_event(text="after"))
        assert len(published) == 1
    finally:
        _transcript.reset(token)


def test_router_exception_does_not_propagate_to_loop() -> None:
    """A mapping error is logged but doesn't crash the producing _event() call."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)

        def bad_map(_e: Any) -> Any:
            raise RuntimeError("boom")

        router._map = bad_map  # type: ignore[method-assign,assignment]
        # tr._event must not raise even though _process → _map → bad_map raises.
        tr._event(_model_event(text="x"))
    finally:
        _transcript.reset(token)


# ---------------------------------------------------------------------------
# Mapping tests — ModelEvent and ToolEvent
# ---------------------------------------------------------------------------


def test_model_event_text_becomes_agent_message_chunk() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(text="hello world"))
        assert len(published) == 1
        notif = published[0]
        assert notif.session_id == session.session_id
        assert isinstance(notif.update, AgentMessageChunk)
        assert _chunk_text(notif.update) == "hello world"
    finally:
        _transcript.reset(token)


def test_model_event_reasoning_becomes_agent_thought_chunk() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(reasoning="thinking deeply"))
        assert len(published) == 1
        update = published[0].update
        assert isinstance(update, AgentThoughtChunk)
        assert _chunk_text(update) == "thinking deeply"
    finally:
        _transcript.reset(token)


def test_redacted_reasoning_uses_summary_not_raw_payload() -> None:
    """Redacted reasoning must emit `summary` (display-safe), never the raw `reasoning` payload.

    Providers store an encrypted/redacted blob in ``reasoning`` when
    redaction is requested; only ``summary`` is safe for display.
    Mirrors ``ContentReasoning.text``'s redaction policy.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        block = ContentReasoning(
            reasoning="ENCRYPTED-DO-NOT-DISPLAY",
            summary="brief safe summary",
            redacted=True,
        )
        tr._event(_model_event(blocks=[block]))
        assert len(published) == 1
        update = published[0].update
        assert isinstance(update, AgentThoughtChunk)
        text = _chunk_text(update)
        assert text == "brief safe summary"
        assert "ENCRYPTED-DO-NOT-DISPLAY" not in text

    finally:
        _transcript.reset(token)


def test_redacted_reasoning_without_summary_emits_empty_text() -> None:
    """If a redacted block has no summary, the chunk text is empty (not the raw payload)."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        block = ContentReasoning(
            reasoning="SECRET-PAYLOAD", summary=None, redacted=True
        )
        tr._event(_model_event(blocks=[block]))
        assert len(published) == 1
        update = published[0].update
        assert isinstance(update, AgentThoughtChunk)
        assert _chunk_text(update) == ""
    finally:
        _transcript.reset(token)


def test_model_event_mixed_text_and_reasoning_emit_in_order() -> None:
    """Reasoning block followed by text block → AgentThoughtChunk then AgentMessageChunk."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        blocks = [
            ContentReasoning(reasoning="ponder"),
            ContentText(text="answer"),
        ]
        tr._event(_model_event(blocks=blocks))
        assert len(published) == 2
        assert isinstance(published[0].update, AgentThoughtChunk)
        assert isinstance(published[1].update, AgentMessageChunk)
    finally:
        _transcript.reset(token)


def test_pending_model_event_emits_nothing() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(text="not yet", pending=True))
        assert published == []
    finally:
        _transcript.reset(token)


def test_empty_model_output_emits_nothing() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(empty_output=True))
        assert published == []
    finally:
        _transcript.reset(token)


def test_tool_event_first_sight_emits_tool_call_start_with_in_progress() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_tool_event(tool_id="tc1", function="weather", pending=True))
        assert len(published) == 1
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.tool_call_id == "tc1"
        assert update.title == "weather"
        assert update.status == "in_progress"
    finally:
        _transcript.reset(token)


def test_tool_event_second_sight_emits_tool_call_progress_completed() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", pending=True)
        tr._event(event)
        # complete it
        event.pending = None
        tr._event_updated(event)
        assert len(published) == 2
        first, second = published
        first_update = first.update
        second_update = second.update
        assert isinstance(first_update, ToolCallStart)
        assert isinstance(second_update, ToolCallProgress)
        assert second_update.tool_call_id == "tc1"
        assert second_update.status == "completed"
    finally:
        _transcript.reset(token)


def test_tool_event_failed_emits_progress_failed_status() -> None:
    from inspect_ai.tool._tool_call import ToolCallError

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", pending=True)
        tr._event(event)
        event.pending = None
        event.error = ToolCallError(type="unknown", message="oops")
        tr._event_updated(event)
        last_update = published[-1].update
        assert isinstance(last_update, ToolCallProgress)
        assert last_update.status == "failed"
    finally:
        _transcript.reset(token)


def test_tool_call_status_helper() -> None:
    """Status helper resolves pending/error/failed/normal correctly."""
    assert _tool_call_status(_tool_event(pending=True)) == "in_progress"
    assert _tool_call_status(_tool_event(error=True)) == "failed"
    assert _tool_call_status(_tool_event()) == "completed"


def test_cancel_current_turn_marks_in_flight_tool_as_failed() -> None:
    """An in-flight tool cancelled via cancel_current_turn surfaces as ToolCallProgress(failed).

    Regression: previously the router emitted status="completed" for
    cancelled tools because cancel_current_turn cleared `pending` but
    left `error`/`failed` unset. ACP clients would render cancelled
    tools as successful.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        # Simulate an in-flight tool call: emit the pending ToolEvent and
        # register it with the session as in-flight.
        event = _tool_event(tool_id="tc1", function="weather", pending=True)
        tr._event(event)
        with session.track_tool_call("tc1", event=event):
            # Producer cancels; cancel_current_turn fires _event_updated.
            session.cancel_current_turn()
        last_update = published[-1].update
        assert isinstance(last_update, ToolCallProgress)
        assert last_update.status == "failed", (
            f"cancelled tool should surface as failed; got status={last_update.status}"
        )
        # The transcript record itself should also reflect cancellation
        # (matches the synthetic ChatMessageTool repair sent by after_cancel).
        assert event.failed is True
        assert event.error is not None and event.error.type == "cancelled"
    finally:
        _transcript.reset(token)


def test_model_event_emits_chunks_exactly_once_for_cache_hit_pattern() -> None:
    """Cache-hit pattern: non-pending event followed by _event_updated emits chunks once.

    Regression: cached ModelEvents are recorded as ``pending=False`` and
    then immediately re-touched by ``complete()`` → ``_event_updated``.
    Without uuid-based dedupe, the router would publish the same chunks
    twice.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        # Build the event with output already populated and pending=False
        # (the cache-hit shape from `_record_model_interaction(output=existing)`).
        event = _model_event(text="cached answer")
        assert event.pending is None
        tr._event(event)
        # complete() then re-emits via _event_updated on the same instance.
        tr._event_updated(event)
        # Expect exactly one AgentMessageChunk, not two.
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 1, (
            f"cached ModelEvent emitted chunks {len(chunks)} times; "
            f"published={[type(n.update).__name__ for n in published]}"
        )
        update = chunks[0].update
        assert isinstance(update, AgentMessageChunk)
        assert _chunk_text(update) == "cached answer"
    finally:
        _transcript.reset(token)


def test_model_event_emits_chunks_exactly_once_for_pending_then_complete_pattern() -> (
    None
):
    """Pending → complete: chunk emits once on the completion update.

    The normal generate flow: event is created with pending=True (empty
    output), then `complete()` fills output and clears pending. Chunks
    should appear once, on the second sighting.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(text="real answer", pending=True)
        tr._event(event)
        # No chunks during pending.
        assert [n for n in published if isinstance(n.update, AgentMessageChunk)] == []
        # Simulate complete(): clear pending, output already populated.
        event.pending = None
        tr._event_updated(event)
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 1
        update = chunks[0].update
        assert isinstance(update, AgentMessageChunk)
        assert _chunk_text(update) == "real answer"
    finally:
        _transcript.reset(token)


def test_inspect_only_events_are_silently_dropped() -> None:
    """Events with no Phase-6 ACP mapping must not publish anything."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        events: list[Event] = [
            InfoEvent(data={"x": 1}),
            CompactionEvent(type="trim", tokens_before=10, tokens_after=5),
            InterruptEvent(source="user_cancel", interrupted="generate"),
            LoggerEvent(
                message=LoggingMessage(level="info", message="hi", created=0.0)
            ),
            StateEvent(changes=[]),
            StoreEvent(changes=[]),
            SampleInitEvent(
                sample={"id": "s", "input": ""},  # type: ignore[arg-type]
                state={},
            ),
            SampleLimitEvent(type="message", message="m"),
            SubtaskEvent(name="t", input={}, type=None, result=None),
        ]
        for e in events:
            tr._event(e)
        assert published == []
    finally:
        _transcript.reset(token)


# ---------------------------------------------------------------------------
# Filter-flag tests
# ---------------------------------------------------------------------------


def test_disable_subagent_filtering_flips_session_flag() -> None:
    session = _new_session()
    assert session._filter_subagent_events is True
    session.disable_subagent_filtering()
    assert session._filter_subagent_events is False


def test_sub_agent_events_publish_when_filter_disabled() -> None:
    """With the filter off, ModelEvents from inside a sub-agent emit chunks."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        session.disable_subagent_filtering()
        _, published = _attach_router(session)
        # Outer model event, sub-agent block, sub-agent model event,
        # outer model event again.
        tr._event(_model_event(text="outer-1"))
        tr._event(_span_begin("inner"))
        tr._event(_model_event(text="inner"))
        tr._event(_span_end("inner"))
        tr._event(_model_event(text="outer-2"))
        texts = [
            _chunk_text(n.update)
            for n in published
            if isinstance(n.update, AgentMessageChunk)
        ]
        assert texts == ["outer-1", "inner", "outer-2"]
    finally:
        _transcript.reset(token)


# ---------------------------------------------------------------------------
# Integration tests — react under acp_session
# ---------------------------------------------------------------------------


def _state(text: str = "go") -> AgentState:
    return AgentState(messages=[ChatMessageUser(content=text)])


async def _drain_until_submit(
    stream: Any, timeout: float = 5.0
) -> list[SessionNotification]:
    """Drain notifications from a subscriber stream until the stream closes."""
    items: list[SessionNotification] = []
    with anyio.move_on_after(timeout):
        async for item in stream:
            items.append(item)
    return items


async def test_router_publishes_for_react_against_mockllm() -> None:
    """End-to-end: react under acp_session emits ModelEvent + ToolEvent notifications."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        # Sequence: turn 1 calls a no-op tool, turn 2 submits "done".
        @tool
        def echo() -> Tool:
            async def execute(text: str) -> str:
                """Echo back the input.

                Args:
                    text: Text to echo.
                """
                return text

            return execute

        outputs = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="echo",
                tool_arguments={"text": "hi"},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            return next(outputs_iter)

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[echo()], model=model)

        async with acp_session() as acp:
            stream = acp.attach()
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: agent(_state()))
                items = await _drain_until_submit(stream, timeout=3.0)

        # We expect ToolCallStart/ToolCallProgress for the echo tool and
        # at least one AgentMessageChunk from a ModelEvent.
        start_titles: list[str] = []
        for i in items:
            if isinstance(i.update, ToolCallStart):
                start_titles.append(i.update.title)
        progress_statuses: list[str | None] = []
        for i in items:
            if isinstance(i.update, ToolCallProgress):
                progress_statuses.append(i.update.status)
        assert "echo" in start_titles, (
            f"expected an echo ToolCallStart; got start_titles={start_titles}"
        )
        # Each tool call should also progress through to completion.
        assert "completed" in progress_statuses
    finally:
        _transcript.reset(token)


async def test_sub_agent_notifications_filtered_by_default() -> None:
    """React with as_tool sub-agent: subscriber sees only outer notifications."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        from inspect_ai.agent._agent import agent as agent_decorator

        @agent_decorator(name="inner_agent", description="A sub-agent.")
        def inner() -> Any:
            async def execute(state: AgentState) -> AgentState:
                # Trigger a transcript event inside the sub-agent so we
                # can verify it was filtered. The inner ModelEvent during
                # an agent run would be filtered by the router; here we
                # just need the boundary span to bracket inner work.
                return state

            return execute

        outputs = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="inner_agent",
                tool_arguments={"input": "do stuff"},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            return next(outputs_iter)

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[as_tool(inner())], model=model)

        async with acp_session() as acp:
            stream = acp.attach()
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: agent(_state()))
                items = await _drain_until_submit(stream, timeout=3.0)

        # No ToolCallStart should have title "inner_agent_internal_*" or any
        # sub-agent-internal tool. The outer "inner_agent" ToolCallStart IS
        # expected (it's the outer model's tool call) — sub-agent internals
        # would only appear if the sub-agent itself made tool calls, which
        # this one does not. The contract we test: nothing extra leaks.
        titles: list[str] = []
        for s in items:
            if isinstance(s.update, ToolCallStart):
                titles.append(s.update.title)
        # We expect the outer "inner_agent" tool call (visible) and possibly
        # "submit" but no sub-agent-internal tool calls.
        assert "inner_agent" in titles
        # Nothing with a "sub_" prefix or similar should appear; this is a
        # negative assertion guarding sub-agent leakage.
        for t in titles:
            assert "_internal" not in t, (
                f"unexpected sub-agent-internal leak in titles: {titles}"
            )
    finally:
        _transcript.reset(token)


async def test_sub_agent_notifications_publish_when_filter_disabled() -> None:
    """With filter disabled, sub-agent ModelEvent chunks reach the subscriber.

    The filter must be disabled on the outer live session BEFORE the
    sub-agent runs (the live router consults the flag on every event).
    react itself opens an inner ``acp_session()`` that becomes a no-op
    shadow — so ``current_acp_session()`` from inside react returns the
    shadow, not the live outer session. We therefore disable filtering
    on the outer ``acp`` handle directly.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        from inspect_ai.agent._agent import agent as agent_decorator

        @agent_decorator(name="inner_with_text", description="A sub-agent.")
        def inner() -> Any:
            async def execute(state: AgentState) -> AgentState:
                # Append a model event from inside the sub-agent's span,
                # so the router sees it at depth>0.
                from inspect_ai.log._transcript import transcript as tr_fn

                ev = _model_event(text="inside-sub-agent")
                tr_fn()._event(ev)
                return state

            return execute

        outputs = [
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="inner_with_text",
                tool_arguments={"input": "go"},
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ]
        outputs_iter = iter(outputs)

        def next_output(input: Any, tools: Any, tc: Any, cfg: Any) -> Any:
            return next(outputs_iter)

        model = get_model("mockllm/model", memoize=False, custom_outputs=next_output)
        agent = react(tools=[as_tool(inner())], model=model)

        async with acp_session() as acp:
            cast(_LiveAcpSession, acp).disable_subagent_filtering()
            stream = acp.attach()
            async with anyio.create_task_group() as tg:
                tg.start_soon(lambda: agent(_state()))
                items = await _drain_until_submit(stream, timeout=3.0)

        texts = [
            _chunk_text(i.update)
            for i in items
            if isinstance(i.update, AgentMessageChunk)
        ]
        assert "inside-sub-agent" in texts, (
            f"sub-agent text missing from subscriber items; got texts={texts}"
        )
    finally:
        _transcript.reset(token)
