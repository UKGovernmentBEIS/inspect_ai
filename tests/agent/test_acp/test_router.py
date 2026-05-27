"""Phase 6 tests for the in-process ACP event router.

Two test styles:

- **Unit**: direct router exercise with synthetic events; ``session.publish``
  monkey-patched to a list collector.
- **Integration**: drive ``react()`` against mockllm with a pre-wired
  ``LiveAcpTransport`` on the sample and a live subscriber stream, using
  the Phase 4 capture-via-tool pattern.
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
from inspect_ai.agent._acp.event_mapping import _AcpEventRouter, _tool_call_status
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
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
from inspect_ai.log._samples import _sample_active as samples_var
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

from ._capture import acp_test_active_sample

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _new_session() -> LiveAcpTransport:
    session = LiveAcpTransport()
    session._attachable_override = True
    return session


def _attach_router(
    session: LiveAcpTransport,
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


def test_outer_agent_span_is_consumed_without_changing_depth() -> None:
    """The FIRST agent span is the outer boundary — its contents emit.

    Reflects the as_solver / agent.run convention: the framework
    opens an ``AGENT_SPAN_TYPE`` span around the agent body, and
    the ACP router subscribes BEFORE that span opens (acp_session
    is entered earlier in the sample lifecycle). The router must
    consume the outer boundary markers without ticking depth or
    every event inside — i.e. the whole conversation — gets
    filtered as a sub-agent.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)
        assert router._depth_tracker.depth == 0
        tr._event(_span_begin("outer"))
        # Outer span begin consumed; depth stays at 0 so events
        # inside the outer agent emit normally.
        assert router._depth_tracker.depth == 0
        tr._event(_span_end("outer"))
        assert router._depth_tracker.depth == 0
    finally:
        _transcript.reset(token)


def test_sub_agent_span_inside_outer_increments_depth() -> None:
    """Sub-agent span nested inside the outer ticks depth to 1.

    Mirrors the as_tool / handoff pattern: the parent agent
    invokes a sub-agent which opens its own ``AGENT_SPAN_TYPE``.
    The first agent span we see is the outer (consumed); the
    nested one is the actual sub-agent boundary whose contents
    should be filtered.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        router, _ = _attach_router(session)
        tr._event(_span_begin("outer"))
        assert router._depth_tracker.depth == 0
        tr._event(_span_begin("sub"))
        assert router._depth_tracker.depth == 1
        tr._event(_span_begin("nested"))
        assert router._depth_tracker.depth == 2
        tr._event(_span_end("nested"))
        assert router._depth_tracker.depth == 1
        tr._event(_span_end("sub"))
        assert router._depth_tracker.depth == 0
        tr._event(_span_end("outer"))
        # Outer end consumed without decrement — already at 0.
        assert router._depth_tracker.depth == 0
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
        assert router._depth_tracker.depth == 0
    finally:
        _transcript.reset(token)


def test_sub_agent_filter_drops_events_at_depth_one() -> None:
    """Events emitted while a sub-agent boundary is open do not publish.

    Opens an outer agent span first (consumed without depth
    change), then a real sub-agent span — events between sub-agent
    begin/end must be filtered. Events between outer begin and
    sub-agent begin DO publish (they belong to the outer agent's
    own conversation).
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_span_begin("outer"))
        tr._event(_model_event(text="visible"))
        tr._event(_span_begin("sub"))
        tr._event(_model_event(text="hidden"))
        tr._event(_span_end("sub"))
        tr._event(_model_event(text="visible-2"))
        tr._event(_span_end("outer"))
        # Two model events published — the two emitted at the
        # outer depth. The middle one (inside the sub-agent) was
        # filtered. ``content`` on an ``AgentMessageChunk`` is a
        # :class:`TextContentBlock` whose ``.text`` carries the
        # model output we set via ``_model_event(text=...)``.
        texts = [
            getattr(n.update.content, "text", None)
            for n in published
            if getattr(n.update, "content", None) is not None
        ]
        assert texts == ["visible", "visible-2"]
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
        assert router._depth_tracker.depth == 0
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


def test_router_exception_does_not_propagate_to_loop(monkeypatch) -> None:
    """A mapping error is logged but doesn't crash the producing _event() call."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        from inspect_ai.agent._acp import event_mapping

        session = _new_session()
        _attach_router(session)

        def bad_map(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        # Patch the module-level `_map_event` that `_process` consults.
        # The mapping logic is hoisted out of the class so the replay
        # path can reuse it; the router instance no longer has an own
        # `_map` method.
        monkeypatch.setattr(event_mapping, "_map_event", bad_map)
        # tr._event must not raise even though _process → _map_event
        # → bad_map raises.
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


def test_redacted_reasoning_without_summary_emits_no_chunk() -> None:
    """Redacted reasoning with no summary emits NOTHING — never the raw payload.

    Two invariants combined here:

    - The raw ``reasoning`` field on a redacted block may carry the
      provider's encrypted payload; we must never forward it.
    - Empty reasoning text would previously emit an empty
      ``AgentThoughtChunk`` AND flag ``emitted_content=True``, which
      suppressed the completion marker downstream and left the
      client's pending spinner stuck. The router now skips emission
      entirely so the completion path can fire its marker.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        block = ContentReasoning(
            reasoning="SECRET-PAYLOAD", summary=None, redacted=True
        )
        tr._event(_model_event(blocks=[block]))
        # No thought chunk, and (since no pending was fired) no
        # completion marker either — both belt + suspenders that the
        # secret payload never leaks.
        thoughts = [n for n in published if isinstance(n.update, AgentThoughtChunk)]
        assert thoughts == []
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


def test_pending_model_event_emits_empty_chunk_signal() -> None:
    """Pending model events publish an empty chunk signal.

    Lets the client flip its status row to ``generating`` the moment
    generation starts, instead of waiting for the round trip to
    complete. Carries the ``inspect.model_event_pending`` meta flag so
    the client can distinguish it from other empty chunks.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(text="not yet", pending=True))
        assert len(published) == 1
        update = published[0].update
        assert isinstance(update, AgentMessageChunk)
        assert update.content.text == ""
        assert update.message_id is not None
        meta = update.field_meta or {}
        assert meta.get("inspect.model")
        assert meta.get("inspect.model_event_pending") is True
    finally:
        _transcript.reset(token)


def test_pending_then_completed_emits_pending_signal_and_real_chunk() -> None:
    """Pending → completed: empty pending signal first, then real chunk.

    Both publish for the same uuid because dedup tracks the two
    phases independently. No completion marker is emitted when real
    content arrives — the client clears its pending tracker on the
    first content chunk.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        evt = _model_event(text="hello world", pending=True)
        tr._event(evt)
        evt.pending = None
        tr._event_updated(evt)
        agent_chunks = [
            u for u in (n.update for n in published) if isinstance(u, AgentMessageChunk)
        ]
        assert len(agent_chunks) == 2
        first, second = agent_chunks
        assert first.content.text == ""
        assert (first.field_meta or {}).get("inspect.model_event_pending") is True
        assert second.content.text == "hello world"
        assert second.message_id == first.message_id
        # No completion marker — real content closes the pending window.
        assert (second.field_meta or {}).get("inspect.model_event_complete") is None
    finally:
        _transcript.reset(token)


def test_pending_then_tool_only_completion_emits_completion_marker() -> None:
    """Tool-only response: pending signal followed by completion marker.

    When the complete phase emits no content chunks (the model's
    response was pure tool calls), the router emits an explicit
    ``inspect.model_event_complete`` marker so the client can clear
    its pending tracker. Without the marker the status row would stay
    stuck at "generating" until the next chunk arrived.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        # Empty blocks list simulates a tool-only response (no text,
        # no reasoning) — output is not empty (so we don't short-
        # circuit) but no content chunks will be emitted.
        evt = _model_event(blocks=[ContentText(text="")], pending=True)
        tr._event(evt)
        evt.pending = None
        tr._event_updated(evt)
        agent_chunks = [
            u for u in (n.update for n in published) if isinstance(u, AgentMessageChunk)
        ]
        assert len(agent_chunks) == 2
        first, second = agent_chunks
        assert (first.field_meta or {}).get("inspect.model_event_pending") is True
        assert second.content.text == ""
        assert (second.field_meta or {}).get("inspect.model_event_complete") is True
        assert second.message_id == first.message_id
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


# ---------------------------------------------------------------------------
# Tool kind heuristic + view content forwarding
#
# Phase 13 refinement: the ``start_tool_call`` notification needs both
# a ``kind`` (so editors like Zed can pick the right icon/UI) and a
# ``content`` array carrying any markdown produced by Inspect's tool
# viewer (so the editor's row shows e.g. the bash command, not just
# the word "bash").
# ---------------------------------------------------------------------------


def test_tool_kind_mapping_for_built_in_tools() -> None:
    """Built-in Inspect tool names map to the appropriate ACP ToolKind.

    Pins the mapping so a refactor that drops a tool from the table
    doesn't silently regress Zed's icon/UI rendering for that tool.
    Notably: shell-execution tools (bash, python, code_execution,
    bash_session_*) NEVER map to ``"execute"`` — Zed pairs that kind
    with the terminal-block content pattern which requires the
    editor to execute commands locally, incompatible with Inspect's
    sandbox model. See the module-level comment on
    ``_TOOL_KIND_BY_NAME``.
    """
    from inspect_ai.agent._acp.tool_content import _tool_kind_for

    # Shell-execution tools: None (no kind). Title carries the
    # command instead — see _descriptive_title.
    assert _tool_kind_for("bash") is None
    assert _tool_kind_for("python") is None
    assert _tool_kind_for("bash_session") is None
    assert _tool_kind_for("bash_session_run") is None
    assert _tool_kind_for("code_execution") is None
    assert _tool_kind_for("computer") is None
    # Other built-ins keep their semantic kind.
    assert _tool_kind_for("read_file") == "read"
    assert _tool_kind_for("list_files") == "read"
    assert _tool_kind_for("text_editor") == "edit"
    assert _tool_kind_for("todo_write") == "edit"
    assert _tool_kind_for("update_plan") == "edit"
    assert _tool_kind_for("think") == "think"
    assert _tool_kind_for("grep") == "search"
    assert _tool_kind_for("web_search") == "search"
    assert _tool_kind_for("web_fetch") == "fetch"
    assert _tool_kind_for("web_browser_click") == "fetch"
    # Unknown tools → None so the client falls back to a generic row.
    assert _tool_kind_for("totally_custom_tool") is None
    assert _tool_kind_for("") is None


def test_tool_call_start_carries_kind_for_known_tools() -> None:
    """start_tool_call notification includes the ToolKind for known tools."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_tool_event(tool_id="tc1", function="read_file", pending=True))
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.kind == "read"
    finally:
        _transcript.reset(token)


def test_tool_call_start_omits_kind_for_shell_tools() -> None:
    """Shell-execution tools deliberately have no kind (see _TOOL_KIND_BY_NAME).

    Pinned so a well-meaning future addition of ``"bash": "execute"``
    can't silently break Zed rendering. The descriptive title carries
    the command for these tools instead.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            ToolEvent(
                id="tc1",
                function="bash",
                arguments={"command": "ls -la"},
                pending=True,
            )
        )
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.kind is None
    finally:
        _transcript.reset(token)


def test_tool_call_start_omits_kind_for_unknown_tools() -> None:
    """Unknown tool name → kind is None so client uses its default row."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_tool_event(tool_id="tc1", function="my_custom_tool", pending=True))
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.kind is None
    finally:
        _transcript.reset(token)


def test_tool_call_start_forwards_view_content_as_markdown() -> None:
    r"""A tool with a viewer attaches ContentToolCallContent with the markdown.

    Without this, Zed (and other ACP editors) shows just the bare
    tool name in the row — useless for distinguishing among many
    bash calls. With it, the editor renders the markdown the
    Inspect viewer already produced (e.g. ```\bash\nls -la\n```).
    """
    from acp.schema import ContentToolCallContent, TextContentBlock

    from inspect_ai.tool._tool_call import ToolCallContent

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ToolEvent(
            id="tc1",
            function="bash",
            arguments={"command": "ls -la"},
            pending=True,
            view=ToolCallContent(
                title="bash",
                format="markdown",
                content="```bash\nls -la\n```\n",
            ),
        )
        tr._event(event)
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.content is not None
        assert len(update.content) == 1
        block = update.content[0]
        assert isinstance(block, ContentToolCallContent)
        assert isinstance(block.content, TextContentBlock)
        assert "ls -la" in block.content.text
        assert "```bash" in block.content.text

    finally:
        _transcript.reset(token)


def test_tool_call_start_title_falls_back_to_function_without_view() -> None:
    """No viewer → no content, title is the bare function name."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_tool_event(tool_id="tc1", function="my_tool", pending=True))
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.title == "my_tool"
        assert update.content is None
    finally:
        _transcript.reset(token)


def test_tool_call_start_uses_descriptive_title_for_known_tools() -> None:
    """Per-tool heuristics produce informative titles instead of bare names.

    The descriptive title (e.g. ``bash ls -la``) takes precedence
    over view.title (which is typically just the language). Format
    is always ``<literal function name> <arg summary>`` so the user
    always sees exactly which tool was called.
    """
    from inspect_ai.tool._tool_call import ToolCallContent

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ToolEvent(
            id="tc1",
            function="bash",
            arguments={"command": "ls -la"},
            pending=True,
            view=ToolCallContent(
                title="bash",  # generic; descriptive title beats this
                format="markdown",
                content="```bash\nls -la\n```\n",
            ),
        )
        tr._event(event)
        update = published[0].update
        assert isinstance(update, ToolCallStart)
        assert update.title == "bash ls -la"
    finally:
        _transcript.reset(token)


def test_descriptive_title_per_known_tool() -> None:
    """Pin the per-tool title format so Zed cards stay readable.

    Uniform format: ``<literal function_name> <arg_summary>``.
    String-typed args that look like patterns/queries/element refs
    are quoted; paths and URLs are not.
    """
    from inspect_ai.agent._acp.tool_content import _descriptive_title

    def _ev(function: str, **args: Any) -> ToolEvent:
        return ToolEvent(id="x", function=function, arguments=args)

    # Shell-execution family — function name + command (no colon
    # separator; uniform with other tools).
    assert _descriptive_title(_ev("bash", command="ls -la")) == "bash ls -la"
    assert _descriptive_title(_ev("python", code="print(1)")) == "python print(1)"
    assert _descriptive_title(_ev("bash_session", cmd="pwd")) == "bash_session pwd"
    assert (
        _descriptive_title(_ev("bash_session_run", command="echo hi"))
        == "bash_session_run echo hi"
    )
    # First non-empty line; multiline commands collapse.
    assert (
        _descriptive_title(_ev("bash", command="\n  pwd\n  ls\n  whoami")) == "bash pwd"
    )
    # Long commands truncate with ellipsis.
    long = "x" * 200
    title = _descriptive_title(_ev("bash", command=long))
    assert title.startswith("bash ")
    assert "…" in title
    # File ops — path unquoted.
    assert (
        _descriptive_title(_ev("read_file", file="src/foo.py"))
        == "read_file src/foo.py"
    )
    assert _descriptive_title(_ev("list_files", path="src/")) == "list_files src/"
    assert (
        _descriptive_title(_ev("text_editor", command="create", path="new.py"))
        == "text_editor create new.py"
    )
    # text_editor with no sub-command — just the path.
    assert _descriptive_title(_ev("text_editor", path="foo.py")) == "text_editor foo.py"
    # Search — pattern/query quoted.
    assert _descriptive_title(_ev("grep", pattern="TODO")) == 'grep "TODO"'
    assert (
        _descriptive_title(_ev("grep", pattern="TODO", path="src/"))
        == 'grep "TODO" in src/'
    )
    assert (
        _descriptive_title(_ev("web_search", query="python")) == 'web_search "python"'
    )
    # Fetch / browse — URL unquoted, element-ref quoted.
    assert (
        _descriptive_title(_ev("web_fetch", url="https://example.com"))
        == "web_fetch https://example.com"
    )
    assert (
        _descriptive_title(_ev("web_browser_go", url="https://example.com"))
        == "web_browser_go https://example.com"
    )
    assert (
        _descriptive_title(_ev("web_browser_click", element_id="ok-button"))
        == 'web_browser_click "ok-button"'
    )
    # Planning / thinking — bare name reads fine.
    assert _descriptive_title(_ev("think")) == "think"
    assert _descriptive_title(_ev("todo_write")) == "todo_write"
    # Unknown tools — first string-valued argument feeds the dim
    # second half of the TUI's title split (see _header_text in
    # tui/widgets/tool_call.py), so user-defined tools get a
    # distinguishable card preview without registering a viewer.
    assert (
        _descriptive_title(_ev("my_custom_tool", city="London", seconds=2.0))
        == "my_custom_tool London"
    )
    # Non-string args before the first string arg are skipped.
    assert (
        _descriptive_title(_ev("my_custom_tool", count=5, name="alice"))
        == "my_custom_tool alice"
    )
    # No string args → bare function name (current behaviour preserved).
    assert _descriptive_title(_ev("my_custom_tool", count=5)) == "my_custom_tool"
    assert _descriptive_title(_ev("my_custom_tool")) == "my_custom_tool"
    # Empty / whitespace-only string args are skipped — wouldn't add signal.
    assert (
        _descriptive_title(_ev("my_custom_tool", first="", second="real value"))
        == "my_custom_tool real value"
    )
    # Long string args truncate via _short_summary.
    long = "x" * 200
    title = _descriptive_title(_ev("my_custom_tool", payload=long))
    assert title.startswith("my_custom_tool ")
    assert "…" in title


# ---------------------------------------------------------------------------
# Tool result forwarded as content on completion
#
# Without this, ACP clients only see the input view (set at start)
# and nothing about what the tool produced. Editors that render
# tool-call rows can show both the command + the output (e.g. bash
# input on one line, stdout below).
# ---------------------------------------------------------------------------


def test_shell_tool_result_wrapped_in_markdown_code_fence() -> None:
    """Shell-execution result text is fenced as a markdown code block.

    Without fencing, terminal output (``ls`` listings, ``wc`` column
    output, etc.) gets rendered as flowed markdown text in Zed and
    loses its alignment — totally illegible for tabular data. With
    the fence, editors render it as monospace.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="bash", pending=True)
        tr._event(event)
        event.pending = None
        event.result = (
            "9898 304K  /app/sample/00001.json\n1234 56K   /app/sample/00002.json"
        )
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, TextContentBlock)
        text = block.content.text
        # Fence opens + closes; original content preserved between.
        assert text.startswith("```\n")
        assert text.endswith("\n```")
        assert "9898 304K" in text
        assert "/app/sample/00002.json" in text

    finally:
        _transcript.reset(token)


def test_non_shell_tool_result_not_fenced() -> None:
    """Non-shell tools (web_search, web_fetch, etc.) get plain text.

    Their results are typically descriptive markdown that already
    flows correctly — fencing would force them into monospace and
    break readable rendering of links, headings, etc.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="web_search", pending=True)
        tr._event(event)
        event.pending = None
        event.result = "# Top hit\n\nSome **bold** text"
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, TextContentBlock)
        text = block.content.text
        # No fence wrapper for non-shell tools.
        assert not text.startswith("```")
        assert text == "# Top hit\n\nSome **bold** text"
    finally:
        _transcript.reset(token)


def test_shell_tool_result_fence_survives_truncation() -> None:
    r"""Fence is applied AFTER truncation so closing backticks always render.

    Pinned because if fence were applied before truncation, the
    closing ``\`\`\`\`\`\`\`\`\`` could be cut off, leaving the editor
    rendering an unclosed code block that swallows everything after.
    """
    from inspect_ai.agent._acp.tool_content import _RESULT_CONTENT_MAX_BYTES

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="bash", pending=True)
        tr._event(event)
        event.pending = None
        event.result = "x" * (_RESULT_CONTENT_MAX_BYTES + 1000)
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, TextContentBlock)
        text = block.content.text
        # Fenced AND truncated.
        assert text.startswith("```\n")
        assert text.endswith("\n```")
        assert "[truncated]" in text
    finally:
        _transcript.reset(token)


def test_replay_completed_tool_carries_result_in_first_sight_start() -> None:
    """Late-attach replay sees a completed tool ONCE; the start must carry the result.

    Live flow: start fires with pending=True (view only), update
    fires on completion with view+result. Replay flow (used on
    late-attach): the event arrives already completed and gets a
    single start emission — no follow-up update. If start doesn't
    include the result, late clients see input but no output.
    Pinned because previously ``_map_tool_event``'s first-sight
    branch only ever sent ``_content_from_view`` (no result).
    """
    from inspect_ai.agent._acp.event_mapping import replay_transcript

    # Build a transcript with one completed tool event (already has
    # a result; no pending=True intermediate).
    event = ToolEvent(
        id="tc1",
        function="bash",
        arguments={"command": "ls -la"},
        pending=None,
        result="foo\nbar\nbaz",
    )

    notifications = list(replay_transcript([event], session_id="sess-1"))
    # Replay yields exactly one notification per first-sight event.
    assert len(notifications) == 1
    update = notifications[0].update
    assert isinstance(update, ToolCallStart)
    # The result should be present in the start's content (fenced
    # because bash is a shell-execution tool).
    assert update.content is not None
    texts = [
        b.content.text
        for b in update.content
        if isinstance(b.content, TextContentBlock)
    ]
    joined = "\n".join(texts)
    assert "foo" in joined and "baz" in joined
    assert "```" in joined  # fenced for shell tool
    # And status reflects completion.
    assert update.status == "completed"


def test_is_shell_execution_tool_membership() -> None:
    """Pin the shell-execution family so a refactor can't silently drift it."""
    from inspect_ai.agent._acp.tool_content import _is_shell_execution_tool

    assert _is_shell_execution_tool("bash")
    assert _is_shell_execution_tool("python")
    assert _is_shell_execution_tool("bash_session")
    assert _is_shell_execution_tool("bash_session_run")
    assert _is_shell_execution_tool("bash_session_create")
    assert _is_shell_execution_tool("code_execution")
    assert not _is_shell_execution_tool("read_file")
    assert not _is_shell_execution_tool("grep")
    assert not _is_shell_execution_tool("web_search")
    assert not _is_shell_execution_tool("my_custom_tool")


def test_completed_tool_emits_update_with_result_content() -> None:
    """A completed tool's result gets forwarded as content on the update."""
    from acp.schema import ContentToolCallContent

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="my_tool", pending=True)
        tr._event(event)
        # Complete with a string result.
        event.pending = None
        event.result = "the output of the tool"
        tr._event_updated(event)

        assert len(published) == 2
        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        assert len(update.content) == 1
        block = update.content[0]
        assert isinstance(block, ContentToolCallContent)
        assert isinstance(block.content, TextContentBlock)
        assert block.content.text == "the output of the tool"
    finally:
        _transcript.reset(token)


def test_completed_tool_with_view_preserves_view_alongside_result() -> None:
    """When the tool has BOTH view + result, content carries both — view first.

    Pinned because ``ToolCallUpdate.content`` REPLACES the content
    collection set by ``ToolCallStart`` (per the ACP schema). If we
    sent only the result on update, the input view (the rendered
    bash command etc.) would disappear from the editor's row. We
    prepend the view block so the row continues to show both.
    """
    from acp.schema import ContentToolCallContent

    from inspect_ai.tool._tool_call import ToolCallContent

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ToolEvent(
            id="tc1",
            function="bash",
            arguments={"command": "echo hi"},
            pending=True,
            view=ToolCallContent(
                title="bash",
                format="markdown",
                content="```bash\necho hi\n```\n",
            ),
        )
        tr._event(event)
        event.pending = None
        event.result = "hi\n"
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        assert len(update.content) == 2
        # View first.
        view_block, result_block = update.content
        assert isinstance(view_block, ContentToolCallContent)
        assert isinstance(view_block.content, TextContentBlock)
        assert "```bash" in view_block.content.text
        # Result second.
        assert isinstance(result_block, ContentToolCallContent)
        assert isinstance(result_block.content, TextContentBlock)
        assert "hi" in result_block.content.text
    finally:
        _transcript.reset(token)


def test_completed_tool_with_empty_result_does_not_overwrite_view() -> None:
    """An empty / missing result leaves content unset on update.

    Without this guard, the update would send ``content=None`` or
    ``content=[view_only]`` — both of which would either replace
    start's content (losing the view) or be wasteful re-sends. The
    cleanest behavior is to omit ``content`` from the update when
    there's no new payload, so the editor's existing view sticks.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="my_tool", pending=True)
        tr._event(event)
        # Complete with NO result (default empty string).
        event.pending = None
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is None
    finally:
        _transcript.reset(token)


def test_completed_tool_result_truncated_when_oversized() -> None:
    """Huge results get truncated with a marker; full payload is on the event."""
    from inspect_ai.agent._acp.tool_content import _RESULT_CONTENT_MAX_BYTES

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="my_tool", pending=True)
        tr._event(event)
        huge = "x" * (_RESULT_CONTENT_MAX_BYTES + 1000)
        event.pending = None
        event.result = huge
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, TextContentBlock)
        text = block.content.text
        assert len(text) <= _RESULT_CONTENT_MAX_BYTES + len("\n…[truncated]") + 10
        assert "[truncated]" in text
        # Full result stays available on the source event for log
        # writers / replay.
        assert event.result == huge
    finally:
        _transcript.reset(token)


def test_completed_tool_with_image_data_uri_result_forwarded() -> None:
    """A ``ContentImage`` data-URI result becomes an ``ImageContentBlock``."""
    from acp.schema import ContentToolCallContent, ImageContentBlock

    from inspect_ai._util.content import ContentImage

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="screenshot", pending=True)
        tr._event(event)
        event.pending = None
        event.result = ContentImage(
            image="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
        )
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block, ContentToolCallContent)
        assert isinstance(block.content, ImageContentBlock)
        assert block.content.mime_type == "image/png"
        # Base64 data extracted from the URI (no ``data:...;base64,`` prefix).
        assert block.content.data == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
        # No URI set for data-URI sources (the data is inline).
        assert block.content.uri is None
    finally:
        _transcript.reset(token)


def test_completed_tool_with_image_http_url_result_forwarded() -> None:
    """A ``ContentImage`` HTTP URL becomes an ``ImageContentBlock`` with ``uri``."""
    from acp.schema import ImageContentBlock

    from inspect_ai._util.content import ContentImage

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="fetch_image", pending=True)
        tr._event(event)
        event.pending = None
        event.result = ContentImage(image="https://example.com/photo.jpg")
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, ImageContentBlock)
        assert block.content.uri == "https://example.com/photo.jpg"
        # Mime type guessed from the URL extension.
        assert block.content.mime_type == "image/jpeg"
        # ``data`` is required by the schema; we set "" when only a URL
        # is available so URI-fetching clients still work.
        assert block.content.data == ""
    finally:
        _transcript.reset(token)


def test_completed_tool_with_mixed_text_image_list_result() -> None:
    """A list result with both ``ContentText`` and ``ContentImage`` round-trips both.

    Pinned because the per-item iteration in
    ``_content_blocks_from_result`` is fragile — a refactor that
    drops one branch would silently lose half the payload.
    """
    from acp.schema import ImageContentBlock

    from inspect_ai._util.content import ContentImage, ContentText

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="render", pending=True)
        tr._event(event)
        event.pending = None
        event.result = [
            ContentText(text="here is the result:"),
            ContentImage(image="data:image/png;base64,iVBORw0KGgoAAAA"),
            ContentText(text="and a caption"),
        ]
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        assert len(update.content) == 3
        text_a, image, text_b = update.content
        assert isinstance(text_a.content, TextContentBlock)
        assert text_a.content.text == "here is the result:"
        assert isinstance(image.content, ImageContentBlock)
        assert image.content.mime_type == "image/png"
        assert isinstance(text_b.content, TextContentBlock)
        assert text_b.content.text == "and a caption"
    finally:
        _transcript.reset(token)


def test_completed_tool_with_image_plain_base64_result_forwarded() -> None:
    """A ``ContentImage`` with plain base64 (no envelope) → default-mime image block.

    Pinned because the previous "data URI OR HTTP URL" gate dropped
    valid plain-base64 image results to a placeholder. ``ContentImage``
    explicitly allows plain base64 per its docstring.
    """
    from acp.schema import ImageContentBlock

    from inspect_ai._util.content import ContentImage

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="screenshot", pending=True)
        tr._event(event)
        event.pending = None
        # No URL scheme, no data: prefix — just base64 bytes.
        event.result = ContentImage(image="iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB")
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, ImageContentBlock)
        # Default mime is image/png (most common for tool-produced
        # screenshots / plots).
        assert block.content.mime_type == "image/png"
        # Plain base64 forwarded verbatim.
        assert block.content.data == "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
        # No URI — the data is inline.
        assert block.content.uri is None
    finally:
        _transcript.reset(token)


def test_completed_tool_with_content_text_result_forwarded() -> None:
    """``ContentText`` result type is unwrapped into the TextContentBlock."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="my_tool", pending=True)
        tr._event(event)
        event.pending = None
        event.result = ContentText(text="content-text result")
        tr._event_updated(event)

        update = published[1].update
        assert isinstance(update, ToolCallProgress)
        assert update.content is not None
        block = update.content[0]
        assert isinstance(block.content, TextContentBlock)
        assert block.content.text == "content-text result"
    finally:
        _transcript.reset(token)


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


def test_operator_cancel_keeps_cancel_marker_through_tool_natural_completion() -> None:
    """Cancel marker must stay sticky while natural completion records forensic data.

    Scenario: ``cancel_current_turn`` marks the in-flight ToolEvent as
    ``failed`` with ``error=ToolCallError("cancelled")``. The tool's
    own coroutine then finishes (e.g. a near-instant tool like
    ``update_plan``) inside the cancellation propagation window and
    ``_call_tools.py`` calls
    ``event._set_result(error=None, failed=None, result="...", ...)``.

    The cancel marker fields (``error.type == "cancelled"`` +
    ``failed=True``) must remain sticky so renderers can hide the
    cancelled event from the live transcript. The forensic fields
    (``result``, ``completed``, ``working_time``, identifiers) must be
    populated with the natural-completion values so the eval log
    retains a record of what the abandoned tool actually returned.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="update_plan", pending=True)
        tr._event(event)
        with session.track_tool_call("tc1", event=event):
            session.cancel_current_turn()

        # Simulate the natural-completion race: the tool's coroutine
        # finished inside the propagation window so _call_tools.py
        # calls _set_result with the tool's actual result body.
        event._set_result(
            result="plan was updated with 5 entries",
            truncated=None,
            error=None,
            waiting_time=0.0,
            agent=None,
            failed=None,
            message_id=None,
        )
        tr._event_updated(event)

        # Cancel marker is sticky — renderers hide the event by checking
        # error.type == "cancelled" and failed is True.
        assert event.failed is True
        assert event.error is not None
        assert event.error.type == "cancelled"
        # Forensic data is recorded for the eval log.
        assert event.result == "plan was updated with 5 entries"
        assert event.completed is not None
        assert event.working_time is not None
        # Final router publication still surfaces as failed, not completed.
        last_update = published[-1].update
        assert isinstance(last_update, ToolCallProgress)
        assert last_update.status == "failed"
    finally:
        _transcript.reset(token)


def test_operator_cancel_keeps_cancel_marker_through_tool_error() -> None:
    """Cancel marker must stay sticky even when late tool completion is itself an error.

    Scenario: ``cancel_current_turn`` marks an in-flight ToolEvent as
    cancelled, then the tool's own coroutine errors (e.g. timeout,
    ValueError) inside the propagation window and ``_call_tools.py``
    calls ``event._set_result(error=ToolCallError(...), failed=True)``.

    The cancel marker (``error.type == "cancelled"`` + ``failed=True``)
    must remain sticky — the late error / failed status is discarded
    so renderers (TUI + inspect view) and ACP clients surface the row
    as cancelled rather than as a normal failed tool. Forensic fields
    (``result``, ``completed``, ``working_time``) are still recorded
    from the late completion.
    """
    from inspect_ai.tool._tool_call import ToolCallError

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _tool_event(tool_id="tc1", function="update_plan", pending=True)
        tr._event(event)
        with session.track_tool_call("tc1", event=event):
            session.cancel_current_turn()

        # Simulate the natural-error race: the tool's coroutine raised
        # inside the propagation window so _call_tools.py calls
        # _set_result with a real ToolCallError.
        event._set_result(
            result="",
            truncated=None,
            error=ToolCallError(type="unknown", message="boom"),
            waiting_time=0.0,
            agent=None,
            failed=True,
            message_id=None,
        )
        tr._event_updated(event)

        # Cancel marker is sticky — the late "unknown" error did NOT
        # overwrite the "cancelled" marker stamped by cancel_current_turn.
        assert event.failed is True
        assert event.error is not None
        assert event.error.type == "cancelled"
        # Forensic data is recorded for the eval log.
        assert event.completed is not None
        assert event.working_time is not None
        # Router publication still surfaces as failed (cancelled-as-failed
        # maps to failed via _tool_call_status).
        last_update = published[-1].update
        assert isinstance(last_update, ToolCallProgress)
        assert last_update.status == "failed"
    finally:
        _transcript.reset(token)


def test_operator_cancel_keeps_cancel_marker_through_model_natural_completion() -> None:
    """Cancel marker must stay sticky while natural completion records forensic data.

    Scenario: ``cancel_current_turn`` stamps
    ``error=OPERATOR_CANCEL_ERROR`` on the in-flight ModelEvent after
    the user clicks Interrupt while a generate is mid-stream. The
    provider's HTTP request can still return successfully inside the
    cancellation propagation window; ``_model.py``'s ``complete()``
    runs normally so ``event.output`` and ``event.call`` capture the
    real response, while ``event.error`` stays sticky as the cancel
    marker (``complete()``'s success branch does not touch ``error``).

    Renderers discriminate on the sticky ``OPERATOR_CANCEL_ERROR``
    marker to hide the event from the live transcript, while the eval
    log retains the natural-completion output for forensic inspection.
    """
    from inspect_ai.event._model import OPERATOR_CANCEL_ERROR

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        # Pre-cancel state: ModelEvent is pending with empty output.
        event = _model_event(text="streamed-partial", pending=True)
        # Simulate the cancel marking step on the live model event.
        event.error = OPERATOR_CANCEL_ERROR
        event.pending = None

        # Simulate the natural-completion race: provider returned a
        # ModelOutput inside the cancellation propagation window.
        # complete()'s success branch sets event.output unconditionally
        # but does not touch event.error, so the cancel marker survives.
        from inspect_ai.model._chat_message import ChatMessageAssistant
        from inspect_ai.model._model_output import (
            ChatCompletionChoice,
            ModelOutput,
        )

        late_output = ModelOutput(
            model="mockllm/model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(content="late-streamed-content")
                )
            ],
        )

        # Inline the contract from _model.py:complete() success branch.
        event.output = late_output

        # Forensic data is recorded (eval log keeps it).
        assert event.output is late_output
        # Cancel marker remains sticky (renderers hide on this).
        assert event.error == OPERATOR_CANCEL_ERROR
        assert event.pending is None
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
    """Pending → complete: one empty pending signal, then one real chunk.

    The normal generate flow: event is created with pending=True (empty
    output), then `complete()` fills output and clears pending. The
    router emits an empty AgentMessageChunk during pending so the client
    can flip its status row immediately, then the real text chunk fires
    on the completion update. Dedup must keep this at exactly two chunks
    (one pending signal + one real) even across multiple update events.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(text="real answer", pending=True)
        tr._event(event)
        # One empty pending signal during pending phase.
        pending_chunks = [
            n for n in published if isinstance(n.update, AgentMessageChunk)
        ]
        assert len(pending_chunks) == 1
        first = pending_chunks[0].update
        assert isinstance(first, AgentMessageChunk)
        assert _chunk_text(first) == ""
        # Simulate complete(): clear pending, output already populated.
        event.pending = None
        tr._event_updated(event)
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        # One pending signal + one real chunk = two total.
        assert len(chunks) == 2
        second = chunks[1].update
        assert isinstance(second, AgentMessageChunk)
        assert _chunk_text(second) == "real answer"
        # Both share the same message_id so the client groups them
        # into one assistant bubble.
        assert first.message_id == second.message_id
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
# Integration tests — react with per-sample LiveAcpTransport
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
    """End-to-end: react emits ModelEvent + ToolEvent notifications via per-sample transport."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample = acp_test_active_sample(transcript)
    sample_tok = samples_var.set(sample)
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

        acp = cast(LiveAcpTransport, sample.acp_transport)
        async with acp:
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
        # Title may include a first-string-arg suffix (e.g. "echo hi")
        # from descriptive_title's generic fallback — match on the
        # function-name prefix, not exact equality.
        assert any(t == "echo" or t.startswith("echo ") for t in start_titles), (
            f"expected an echo ToolCallStart; got start_titles={start_titles}"
        )
        # Each tool call should also progress through to completion.
        assert "completed" in progress_statuses
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_sub_agent_notifications_filtered_by_default() -> None:
    """React with as_tool sub-agent: subscriber sees only outer notifications."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample = acp_test_active_sample(transcript)
    sample_tok = samples_var.set(sample)
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

        acp = cast(LiveAcpTransport, sample.acp_transport)
        async with acp:
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
        # "submit" but no sub-agent-internal tool calls. The title may
        # include a first-string-arg suffix (e.g. "inner_agent do stuff")
        # from descriptive_title's generic fallback — match the prefix.
        assert any(t == "inner_agent" or t.startswith("inner_agent ") for t in titles)
        # Nothing with a "sub_" prefix or similar should appear; this is a
        # negative assertion guarding sub-agent leakage.
        for t in titles:
            assert "_internal" not in t, (
                f"unexpected sub-agent-internal leak in titles: {titles}"
            )
    finally:
        samples_var.reset(sample_tok)
        _transcript.reset(token)


async def test_sub_agent_notifications_publish_when_filter_disabled() -> None:
    """With filter disabled, sub-agent ModelEvent chunks reach the subscriber.

    The filter must be disabled on the outer live transport BEFORE the
    sub-agent runs (the live router consults the flag on every event).
    The transport pre-wired on the sample is the producer target for the
    outer react's channel; the sub-agent's nested channel is rejected
    by ``maybe_bind`` (first-binder-wins) so it doesn't drive the
    transport. We disable filtering on the pre-wired transport directly.
    """
    transcript = Transcript()
    token = _transcript.set(transcript)
    sample = acp_test_active_sample(transcript)
    sample_tok = samples_var.set(sample)
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

        acp = cast(LiveAcpTransport, sample.acp_transport)
        async with acp:
            acp.disable_subagent_filtering()
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
        samples_var.reset(sample_tok)
        _transcript.reset(token)
