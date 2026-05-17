"""Phase 2 (TUI) tests for router emissions: message_id, _meta.inspect.model, UsageUpdate.

Phase 2 of the standalone ACP TUI requires the router to populate three
things that Phase 6 left optional/absent:

- ``ContentChunk.message_id`` — used by the client to group successive
  chunks into one rendered message (per ACP semantics: change in
  ``messageId`` indicates a new message). Source: ``ModelEvent.uuid``,
  so all chunks from one model call share an id and the id round-trips
  back to the originating event.
- ``ContentChunk._meta["inspect.model"]`` — drives the meta-row
  "model X" chip on the client. Per-chunk (not session-static) so the
  chip stays correct across multi-model evals.
- ``UsageUpdate`` (native ACP) — drives the "tokens N/M" chip. Emitted
  after each ModelEvent's chunks when the model's context window can be
  looked up via ``get_model_info``.
"""

from typing import Any
from uuid import UUID

from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    ContentToolCallContent,
    FileEditToolCallContent,
    SessionNotification,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent._acp._router import (
    _TOOL_KIND_BY_NAME,
    _AcpEventRouter,
    _model_event_message_id,
    _tool_kind_for,
)
from inspect_ai.agent._acp._session import _LiveAcpSession
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import ChatMessageAssistant, ModelInfo, set_model_info
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool._tool_call import ToolCall

# Use a synthetic model name we register with set_model_info so the
# UsageUpdate path doesn't depend on the real model DB and can't be
# broken by changes to the canonical model data files.
_TEST_MODEL = "phase2-router-test/synthetic"
_TEST_CONTEXT_LENGTH = 100_000

set_model_info(
    _TEST_MODEL,
    ModelInfo(context_length=_TEST_CONTEXT_LENGTH, output_tokens=4096),
)


def _new_session() -> _LiveAcpSession:
    return _LiveAcpSession()


def _attach_router(
    session: _LiveAcpSession,
) -> tuple[_AcpEventRouter, list[SessionNotification]]:
    published: list[SessionNotification] = []
    session.publish = published.append  # type: ignore[method-assign,assignment]
    router = _AcpEventRouter(session)
    router.attach()
    return router, published


def _model_event(
    *,
    text: str | None = None,
    reasoning: str | None = None,
    tool_calls: list[ToolCall] | None = None,
    model: str = _TEST_MODEL,
    usage: ModelUsage | None = None,
) -> ModelEvent:
    blocks: list[Any] = []
    if reasoning is not None:
        blocks.append(ContentReasoning(reasoning=reasoning))
    if text is not None:
        blocks.append(ContentText(text=text))
    message = ChatMessageAssistant(
        content=blocks if blocks else "",
        tool_calls=tool_calls,
    )
    output = ModelOutput(
        model=model,
        choices=[ChatCompletionChoice(message=message)],
        usage=usage,
    )
    return ModelEvent(
        model=model,
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=output,
    )


# ---------------------------------------------------------------------------
# A1: message_id population
# ---------------------------------------------------------------------------


def test_text_chunk_message_id_is_uuidv5_of_model_event_uuid() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(text="hello")
        tr._event(event)
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 1
        assert event.uuid is not None
        assert chunks[0].update.message_id == _model_event_message_id(event.uuid)
        # ACP schema mandates RFC 4122 UUID format for message ids.
        UUID(chunks[0].update.message_id)
    finally:
        _transcript.reset(token)


def test_message_id_round_trips_via_meta() -> None:
    """_meta['inspect.model_event_uuid'] carries the original shortuuid."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(text="hello")
        tr._event(event)
        chunk = next(
            n.update for n in published if isinstance(n.update, AgentMessageChunk)
        )
        assert chunk.field_meta is not None
        assert chunk.field_meta["inspect.model_event_uuid"] == event.uuid
    finally:
        _transcript.reset(token)


def test_thought_chunk_message_id_is_uuidv5_of_model_event_uuid() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(reasoning="why")
        tr._event(event)
        chunks = [n for n in published if isinstance(n.update, AgentThoughtChunk)]
        assert len(chunks) == 1
        assert event.uuid is not None
        assert chunks[0].update.message_id == _model_event_message_id(event.uuid)
    finally:
        _transcript.reset(token)


def test_text_and_thought_from_same_event_share_message_id() -> None:
    """Reasoning + text from one ModelEvent are one logical assistant message."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(reasoning="thinking", text="response")
        tr._event(event)
        chunks = [
            n.update
            for n in published
            if isinstance(n.update, (AgentMessageChunk, AgentThoughtChunk))
        ]
        assert len(chunks) == 2
        assert event.uuid is not None
        expected = _model_event_message_id(event.uuid)
        assert chunks[0].message_id == expected
        assert chunks[1].message_id == expected
    finally:
        _transcript.reset(token)


def test_separate_model_events_get_distinct_message_ids() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        e1 = _model_event(text="one")
        e2 = _model_event(text="two")
        tr._event(e1)
        tr._event(e2)
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 2
        assert chunks[0].update.message_id != chunks[1].update.message_id
        assert e1.uuid is not None and e2.uuid is not None
        assert chunks[0].update.message_id == _model_event_message_id(e1.uuid)
        assert chunks[1].update.message_id == _model_event_message_id(e2.uuid)
    finally:
        _transcript.reset(token)


def test_message_id_derivation_is_deterministic() -> None:
    """Same Inspect uuid → same message_id (stable across runs)."""
    assert _model_event_message_id("abc123") == _model_event_message_id("abc123")
    assert _model_event_message_id("abc123") != _model_event_message_id("abc124")


# ---------------------------------------------------------------------------
# A3: _meta["inspect.model"] population
# ---------------------------------------------------------------------------


def test_agent_message_chunk_meta_carries_model_name() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(text="hi", model=_TEST_MODEL))
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 1
        assert chunks[0].update.field_meta is not None
        assert chunks[0].update.field_meta["inspect.model"] == _TEST_MODEL
    finally:
        _transcript.reset(token)


def test_agent_thought_chunk_meta_carries_model_name() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(reasoning="hmm", model=_TEST_MODEL))
        chunks = [n for n in published if isinstance(n.update, AgentThoughtChunk)]
        assert len(chunks) == 1
        assert chunks[0].update.field_meta is not None
        assert chunks[0].update.field_meta["inspect.model"] == _TEST_MODEL
    finally:
        _transcript.reset(token)


def test_chunks_from_different_events_can_carry_different_models() -> None:
    """Multi-model evals: each chunk's meta reflects its originating event."""
    set_model_info(
        "phase2-router-test/synthetic-2",
        ModelInfo(context_length=50_000, output_tokens=2048),
    )
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(_model_event(text="from a", model=_TEST_MODEL))
        tr._event(_model_event(text="from b", model="phase2-router-test/synthetic-2"))
        chunks = [
            n.update for n in published if isinstance(n.update, AgentMessageChunk)
        ]
        assert chunks[0].field_meta is not None
        assert chunks[0].field_meta["inspect.model"] == _TEST_MODEL
        assert chunks[1].field_meta is not None
        assert chunks[1].field_meta["inspect.model"] == "phase2-router-test/synthetic-2"
    finally:
        _transcript.reset(token)


# ---------------------------------------------------------------------------
# A2: UsageUpdate emission
# ---------------------------------------------------------------------------


def test_usage_update_emitted_after_text_chunk() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            _model_event(
                text="hi",
                usage=ModelUsage(
                    input_tokens=1000, output_tokens=200, total_tokens=1200
                ),
            )
        )
        usages = [n for n in published if isinstance(n.update, UsageUpdate)]
        assert len(usages) == 1
        assert usages[0].update.used == 1200
        assert usages[0].update.size == _TEST_CONTEXT_LENGTH
    finally:
        _transcript.reset(token)


def test_usage_update_includes_cached_tokens() -> None:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            _model_event(
                text="hi",
                usage=ModelUsage(
                    input_tokens=500,
                    output_tokens=100,
                    total_tokens=600,
                    input_tokens_cache_read=300,
                    input_tokens_cache_write=200,
                ),
            )
        )
        usages = [n.update for n in published if isinstance(n.update, UsageUpdate)]
        assert len(usages) == 1
        # 500 (uncached input) + 100 (output) + 300 (cache read) + 200 (cache write)
        assert usages[0].used == 1100
    finally:
        _transcript.reset(token)


def test_usage_update_skipped_when_model_unknown_to_registry() -> None:
    """No size lookup → no UsageUpdate (schema requires size)."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            _model_event(
                text="hi",
                model="totally-made-up-provider/never-registered-model",
                usage=ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )
        )
        usages = [n for n in published if isinstance(n.update, UsageUpdate)]
        assert usages == []
        # Text chunk still emits.
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 1
    finally:
        _transcript.reset(token)


def test_usage_update_order_after_chunks() -> None:
    """UsageUpdate is emitted after all chunks for this turn.

    The client wants conversation context to land before the chip
    updates so the chip change visually corresponds to the model call
    just rendered.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            _model_event(
                reasoning="thinking",
                text="response",
                usage=ModelUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            )
        )
        kinds = [type(n.update).__name__ for n in published]
        assert kinds == ["AgentThoughtChunk", "AgentMessageChunk", "UsageUpdate"]
    finally:
        _transcript.reset(token)


def test_usage_update_emitted_for_tool_call_only_response() -> None:
    """A common assistant turn is ``content=""`` + ``tool_calls``.

    No text/reasoning chunks render, but real tokens were consumed.
    The chip MUST update so token tracking doesn't go stale through
    tool-loop turns. The router also emits a completion-marker chunk
    (empty content, ``inspect.model_event_complete=True``) so the
    client can close out the pending-generation status row — but only
    when a pending marker was sent earlier. This test mirrors the
    real flow: pending fires when the model call begins, complete
    fires when it returns (tool-only).
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = _model_event(
            tool_calls=[ToolCall(id="tc1", function="my_tool", arguments={})],
            usage=ModelUsage(input_tokens=500, output_tokens=20, total_tokens=520),
        )
        # Pending phase first — emits the spinner-start chunk.
        event.pending = True
        tr._event(event)
        # Then completion — same event, pending cleared.
        event.pending = None
        tr._event_updated(event)
        # Exactly two AgentMessageChunks: the pending opener + the
        # completion marker. Both empty content; the marker carries
        # ``inspect.model_event_complete``.
        chunks = [n for n in published if isinstance(n.update, AgentMessageChunk)]
        assert len(chunks) == 2
        opener = chunks[0].update
        marker = chunks[1].update
        assert (opener.field_meta or {}).get("inspect.model_event_pending") is True
        assert isinstance(marker, AgentMessageChunk)
        assert marker.content.text == ""
        assert (marker.field_meta or {}).get("inspect.model_event_complete") is True
        assert not any(isinstance(n.update, AgentThoughtChunk) for n in published)
        usages = [n.update for n in published if isinstance(n.update, UsageUpdate)]
        assert len(usages) == 1
        assert usages[0].used == 520
        assert usages[0].size == _TEST_CONTEXT_LENGTH
    finally:
        _transcript.reset(token)


def test_empty_output_after_pending_still_emits_completion_marker() -> None:
    """Error / cancel / empty completion must clear the client's spinner.

    Regression for P1 from review: previously the empty-output path
    returned early without a completion marker, so a pending event
    that finished with no content (error, cancel, or genuinely empty
    output) left the assistant chip stuck spinning forever.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ModelEvent(
            model=_TEST_MODEL,
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(model=_TEST_MODEL, choices=[]),
        )
        assert event.output.empty
        # Pending → spinner starts.
        event.pending = True
        tr._event(event)
        # Then the event completes empty (no choices arrived).
        event.pending = None
        tr._event_updated(event)
        markers = [
            n
            for n in published
            if isinstance(n.update, AgentMessageChunk)
            and (n.update.field_meta or {}).get("inspect.model_event_complete") is True
        ]
        assert len(markers) == 1
        # And on a re-delivery the marker doesn't double-emit.
        tr._event_updated(event)
        markers_again = [
            n
            for n in published
            if isinstance(n.update, AgentMessageChunk)
            and (n.update.field_meta or {}).get("inspect.model_event_complete") is True
        ]
        assert len(markers_again) == 1
    finally:
        _transcript.reset(token)


def test_empty_reasoning_completion_still_emits_marker() -> None:
    """Reasoning blocks with empty text must not suppress the marker.

    Regression for P1 from review: the reasoning branch previously
    set ``emitted_content = True`` even when the reasoning text was
    empty (redacted reasoning with no summary, or a zero-thinking
    response). With the marker suppressed and no real content to
    clear pending, the client's spinner stayed stuck.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        # Build a message whose only block is empty reasoning.
        empty_reasoning = ContentReasoning(reasoning="", redacted=False)
        message = ChatMessageAssistant(content=[empty_reasoning])
        output = ModelOutput(
            model=_TEST_MODEL, choices=[ChatCompletionChoice(message=message)]
        )
        event = ModelEvent(
            model=_TEST_MODEL,
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=output,
        )
        event.pending = True
        tr._event(event)
        event.pending = None
        tr._event_updated(event)
        # No reasoning chunk should have been emitted for the empty
        # text — and a completion marker should have fired.
        assert not any(isinstance(n.update, AgentThoughtChunk) for n in published)
        markers = [
            n
            for n in published
            if isinstance(n.update, AgentMessageChunk)
            and (n.update.field_meta or {}).get("inspect.model_event_complete") is True
        ]
        assert len(markers) == 1
    finally:
        _transcript.reset(token)


def test_cache_hit_empty_output_emits_no_marker() -> None:
    """No pending was sent → no marker (would create an empty bubble).

    The completion marker only makes sense when there's a pending
    spinner to clear. A bare empty event with no preceding pending
    shouldn't manufacture a phantom assistant bubble.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ModelEvent(
            model=_TEST_MODEL,
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(model=_TEST_MODEL, choices=[]),
        )
        assert event.output.empty
        # Straight to complete — no pending phase.
        tr._event(event)
        assert published == []
    finally:
        _transcript.reset(token)


def test_no_publications_when_output_is_truly_empty() -> None:
    """No choices in ModelOutput → no chunks AND no UsageUpdate.

    The top-of-function ``event.output.empty`` guard short-circuits
    before usage emission. Protects against publishing usage for
    placeholder / pending events that haven't actually run yet.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        event = ModelEvent(
            model=_TEST_MODEL,
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(model=_TEST_MODEL, choices=[]),
        )
        assert event.output.empty
        tr._event(event)
        assert published == []
    finally:
        _transcript.reset(token)


# ---------------------------------------------------------------------------
# A4: FileEditToolCallContent for edit-family tools
# ---------------------------------------------------------------------------


def _tool_event_completed(
    *,
    tool_id: str = "tc1",
    function: str,
    arguments: dict | None = None,
    result: str = "ok",
) -> ToolEvent:
    return ToolEvent(
        id=tool_id,
        function=function,
        arguments=arguments or {},
        result=result,
        pending=None,
    )


def _publish_tool(event: ToolEvent) -> list[SessionNotification]:
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(event)
        return published
    finally:
        _transcript.reset(token)


def test_text_editor_create_emits_file_edit_diff() -> None:
    notifs = _publish_tool(
        _tool_event_completed(
            function="text_editor",
            arguments={
                "command": "create",
                "path": "/foo/bar.py",
                "file_text": "print('hi')\n",
            },
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    assert len(starts) == 1
    content = starts[0].content
    assert content is not None
    assert len(content) == 1
    diff = content[0]
    assert isinstance(diff, FileEditToolCallContent)
    assert diff.path == "/foo/bar.py"
    assert diff.old_text is None  # new file
    assert diff.new_text == "print('hi')\n"


def test_text_editor_str_replace_emits_file_edit_diff() -> None:
    notifs = _publish_tool(
        _tool_event_completed(
            function="text_editor",
            arguments={
                "command": "str_replace",
                "path": "/foo/bar.py",
                "old_str": "old line",
                "new_str": "new line",
            },
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    content = starts[0].content
    assert content is not None
    diff = content[0]
    assert isinstance(diff, FileEditToolCallContent)
    assert diff.path == "/foo/bar.py"
    assert diff.old_text == "old line"
    assert diff.new_text == "new line"


def test_text_editor_str_replace_with_none_new_str_renders_empty_new_text() -> None:
    """str_replace with new_str=None means 'delete old_str' — represent as empty new_text."""
    notifs = _publish_tool(
        _tool_event_completed(
            function="text_editor",
            arguments={
                "command": "str_replace",
                "path": "/foo/bar.py",
                "old_str": "to delete",
                # new_str omitted
            },
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    assert starts[0].content is not None
    diff = starts[0].content[0]
    assert isinstance(diff, FileEditToolCallContent)
    assert diff.old_text == "to delete"
    assert diff.new_text == ""


def test_text_editor_view_falls_through_to_generic_content() -> None:
    """View is not an edit; no diff content emitted."""
    notifs = _publish_tool(
        _tool_event_completed(
            function="text_editor",
            arguments={"command": "view", "path": "/foo/bar.py"},
            result="line 1\nline 2\n",
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    content = starts[0].content
    assert content is not None
    assert not any(isinstance(c, FileEditToolCallContent) for c in content)
    assert all(isinstance(c, ContentToolCallContent) for c in content)


def test_text_editor_insert_falls_through_to_generic_content() -> None:
    """Insert is line-positional; loses meaning as a raw diff — skip to generic."""
    notifs = _publish_tool(
        _tool_event_completed(
            function="text_editor",
            arguments={
                "command": "insert",
                "path": "/foo/bar.py",
                "insert_line": 5,
                "insert_text": "inserted",
            },
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    content = starts[0].content
    if content is not None:
        assert not any(isinstance(c, FileEditToolCallContent) for c in content)


def test_non_edit_tool_no_file_edit_content() -> None:
    notifs = _publish_tool(
        _tool_event_completed(
            function="read_file",
            arguments={"file": "/foo/bar.py"},
            result="contents",
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    content = starts[0].content
    if content is not None:
        assert not any(isinstance(c, FileEditToolCallContent) for c in content)


def test_file_edit_diff_carries_through_update_notification() -> None:
    """An in-flight edit completing later gets the diff on the update too.

    Also verifies the pending start does NOT include the diff — the
    edit hasn't actually happened until the result lands.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        pending = ToolEvent(
            id="tc1",
            function="text_editor",
            arguments={
                "command": "create",
                "path": "/foo/bar.py",
                "file_text": "hi",
            },
            pending=True,
        )
        tr._event(pending)
        # Pending start: no diff yet.
        starts = [n.update for n in published if isinstance(n.update, ToolCallStart)]
        assert len(starts) == 1
        if starts[0].content is not None:
            assert not any(
                isinstance(c, FileEditToolCallContent) for c in starts[0].content
            )
        # Completion update: diff appears.
        completed = ToolEvent(
            id="tc1",
            function="text_editor",
            arguments={
                "command": "create",
                "path": "/foo/bar.py",
                "file_text": "hi",
            },
            result="ok",
        )
        tr._event(completed)
        updates = [
            n.update for n in published if isinstance(n.update, ToolCallProgress)
        ]
        assert len(updates) == 1
        content = updates[0].content
        assert content is not None
        assert isinstance(content[0], FileEditToolCallContent)
    finally:
        _transcript.reset(token)


def test_failed_str_replace_does_not_emit_diff() -> None:
    """A str_replace whose old_str wasn't found / wasn't unique fails.

    Without gating, the diff would still render as if the edit had
    succeeded (the args alone look valid). Gate ensures failed events
    fall through to generic content showing the error message.
    """
    from inspect_ai.tool._tool_call import ToolCallError

    notifs = _publish_tool(
        ToolEvent(
            id="tc1",
            function="text_editor",
            arguments={
                "command": "str_replace",
                "path": "/foo/bar.py",
                "old_str": "missing",
                "new_str": "replacement",
            },
            error=ToolCallError(type="unknown", message="No match for old_str"),
            result="",
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    assert len(starts) == 1
    content = starts[0].content
    if content is not None:
        assert not any(isinstance(c, FileEditToolCallContent) for c in content)
    assert starts[0].status == "failed"


def test_failed_create_does_not_emit_diff() -> None:
    """Same gate applied to create.

    A sandboxed write that errored (no perms, no disk, etc.) must not
    render a diff that looks like it succeeded.
    """
    from inspect_ai.tool._tool_call import ToolCallError

    notifs = _publish_tool(
        ToolEvent(
            id="tc1",
            function="text_editor",
            arguments={
                "command": "create",
                "path": "/foo/bar.py",
                "file_text": "hi",
            },
            error=ToolCallError(type="unknown", message="Permission denied"),
        )
    )
    starts = [n.update for n in notifs if isinstance(n.update, ToolCallStart)]
    content = starts[0].content
    if content is not None:
        assert not any(isinstance(c, FileEditToolCallContent) for c in content)


# ---------------------------------------------------------------------------
# A5: ToolCall.locations — intentionally NOT populated.
# Inspect tools run inside sandboxed eval environments; their paths usually
# don't map to the editor's workspace. Surfacing them as ACP locations would
# point "open this file" affordances at paths the editor can't resolve.
# Pinning this with a test so a future "obvious enhancement" can't silently
# re-enable it without revisiting the path-mapping question.
# ---------------------------------------------------------------------------


def test_tool_call_locations_intentionally_unset() -> None:
    for fn, args in (
        ("read_file", {"file_path": "/sandbox/foo.py"}),
        ("text_editor", {"command": "view", "path": "/sandbox/foo.py"}),
        ("list_files", {"path": "/sandbox"}),
    ):
        notifs = _publish_tool(_tool_event_completed(function=fn, arguments=args))
        start = next(n.update for n in notifs if isinstance(n.update, ToolCallStart))
        assert start.locations is None, (
            f"{fn} must not populate ToolCall.locations — sandbox paths don't "
            f"map to editor workspace"
        )


# ---------------------------------------------------------------------------
# A6: ToolKind mapping conservative audit (regression guard)
# ---------------------------------------------------------------------------


def test_shell_execution_tools_remain_unmapped() -> None:
    """Shell tools must never get ``ToolKind="execute"``.

    Reason (see _router.py:_TOOL_KIND_BY_NAME comment + project memory):
    Inspect tools run inside sandboxed eval environments (often remote
    Docker), not on the editor-local machine that ACP's execute kind
    implies. Mapping execute here would make Zed render a terminal
    expecting native streaming we don't implement, hiding our rich
    content. Pinning this with a test so a future "obvious cleanup"
    can't silently flip it.
    """
    for fn in ("bash", "python", "bash_session", "code_execution"):
        assert _tool_kind_for(fn) is None, f"{fn} must not have a ToolKind"


def test_known_safe_mappings_preserved() -> None:
    """Audit guard: confirm the small set of safe-to-map tools is intact."""
    assert _TOOL_KIND_BY_NAME["read_file"] == "read"
    assert _TOOL_KIND_BY_NAME["list_files"] == "read"
    assert _TOOL_KIND_BY_NAME["text_editor"] == "edit"
    assert _TOOL_KIND_BY_NAME["grep"] == "search"
    assert _TOOL_KIND_BY_NAME["web_search"] == "search"
    assert _TOOL_KIND_BY_NAME["web_fetch"] == "fetch"
    assert _TOOL_KIND_BY_NAME["think"] == "think"
    # Web browser prefix family.
    assert _tool_kind_for("web_browser_go") == "fetch"
    assert _tool_kind_for("web_browser_click") == "fetch"


def test_interactive_and_meta_tools_unmapped() -> None:
    """``computer`` / ``memory`` / ``skill`` stay unmapped.

    ``computer`` is interactive (screenshots + clicks) — wrong fit for
    every available ToolKind. ``memory`` is a virtual store, not a real
    filesystem. ``skill`` is a meta-tool that dispatches other tools.
    Mapping any of these would either trigger wrong editor UI or
    misrepresent semantics; the conservative call is to stay unmapped
    and let editors render generic tool rows.
    """
    for fn in ("computer", "memory", "skill"):
        assert _tool_kind_for(fn) is None, f"{fn} must not have a ToolKind"


# ---------------------------------------------------------------------------
# Input-message emission: user + system messages prior to current generation
# ---------------------------------------------------------------------------


def _model_event_with_input(
    input_messages: list[Any],
    *,
    text: str = "ok",
    model: str = _TEST_MODEL,
) -> ModelEvent:
    """ModelEvent factory that populates ``input`` (the standard helper leaves it empty)."""
    message = ChatMessageAssistant(content=text)
    output = ModelOutput(model=model, choices=[ChatCompletionChoice(message=message)])
    return ModelEvent(
        model=model,
        input=input_messages,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=output,
    )


def _user_chunks(notifications: list[SessionNotification]) -> list[Any]:
    from acp.schema import UserMessageChunk

    return [n.update for n in notifications if isinstance(n.update, UserMessageChunk)]


def test_first_model_event_emits_initial_system_and_user_messages() -> None:
    """Walking input backwards on the first turn surfaces the prompt."""
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    sys_msg = ChatMessageSystem(content="you are helpful")
    user_msg = ChatMessageUser(content="hello there", source="input")
    event = _model_event_with_input([sys_msg, user_msg])

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(event)
        user_chunks = _user_chunks(published)
    finally:
        _transcript.reset(token)
    # System first, then user, in input order.
    assert len(user_chunks) == 2
    assert user_chunks[0].content.text == "you are helpful"
    assert user_chunks[1].content.text == "hello there"
    assert (user_chunks[0].field_meta or {}).get("inspect.message_role") == "system"
    assert (user_chunks[1].field_meta or {}).get("inspect.user_source") == "input"


def test_subsequent_model_event_emits_only_messages_after_previous_assistant() -> None:
    """Per-id dedup AND the "walk back to last assistant" cut prevent re-emission."""
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    sys_msg = ChatMessageSystem(content="sys")
    user1 = ChatMessageUser(content="first prompt", source="input")
    asst1 = ChatMessageAssistant(content="first reply")
    user2 = ChatMessageUser(content="follow-up", source="operator")

    # First model call: just sys + user1 in input.
    event1 = _model_event_with_input([sys_msg, user1], text="first reply")
    # Second model call: full history plus the operator's follow-up.
    event2 = _model_event_with_input(
        [sys_msg, user1, asst1, user2], text="second reply"
    )

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(event1)
        tr._event(event2)
        user_chunks = _user_chunks(published)
    finally:
        _transcript.reset(token)
    # Three total — sys + user1 from event1, user2 from event2. The
    # walk-back-to-assistant logic prevents sys + user1 from
    # re-emitting on event2; per-id dedup is the belt to that
    # suspenders.
    assert [c.content.text for c in user_chunks] == [
        "sys",
        "first prompt",
        "follow-up",
    ]
    assert (user_chunks[2].field_meta or {}).get("inspect.user_source") == "operator"


def test_tool_messages_in_input_are_skipped() -> None:
    """Tool messages flow via ToolEvent — UserMessageChunk would double-render."""
    from inspect_ai.model import ChatMessageTool, ChatMessageUser

    user_msg = ChatMessageUser(content="run a thing", source="input")
    tool_msg = ChatMessageTool(content="tool output", tool_call_id="tc-1")
    event = _model_event_with_input([user_msg, tool_msg])

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(event)
        user_chunks = _user_chunks(published)
    finally:
        _transcript.reset(token)
    texts = [c.content.text for c in user_chunks]
    assert "run a thing" in texts
    assert "tool output" not in texts


def test_user_source_none_is_carried_explicitly() -> None:
    """``None`` source survives the meta round-trip as JSON null."""
    from inspect_ai.model import ChatMessageUser

    user_msg = ChatMessageUser(content="bare prompt")  # source defaults to None
    assert user_msg.source is None
    event = _model_event_with_input([user_msg])

    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(event)
        user_chunks = _user_chunks(published)
    finally:
        _transcript.reset(token)
    assert len(user_chunks) == 1
    meta = user_chunks[0].field_meta or {}
    # Explicit None, not the key missing — clients can tell "we know
    # there's no source" from "the server forgot to send it."
    assert "inspect.user_source" in meta
    assert meta["inspect.user_source"] is None
