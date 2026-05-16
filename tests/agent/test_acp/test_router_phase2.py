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
    SessionNotification,
    UsageUpdate,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent._acp._router import _AcpEventRouter, _model_event_message_id
from inspect_ai.agent._acp._session import _LiveAcpSession
from inspect_ai.event._model import ModelEvent
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
    tool-loop turns.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        session = _new_session()
        _, published = _attach_router(session)
        tr._event(
            _model_event(
                tool_calls=[ToolCall(id="tc1", function="my_tool", arguments={})],
                usage=ModelUsage(input_tokens=500, output_tokens=20, total_tokens=520),
            )
        )
        assert not any(
            isinstance(n.update, (AgentMessageChunk, AgentThoughtChunk))
            for n in published
        )
        usages = [n.update for n in published if isinstance(n.update, UsageUpdate)]
        assert len(usages) == 1
        assert usages[0].used == 520
        assert usages[0].size == _TEST_CONTEXT_LENGTH
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
