"""Attachment resolution when reading transcript events.

Regression coverage for the bounded-transcript work (#4062), which routed
``Transcript.events`` reads through the buffer history provider. The provider
returned events whose content was still condensed to ``attachment://<hash>``
references, and nothing downstream resolved them — so consumers that display
content (notably the ACP client) showed bare ``attachment://`` refs in place
of system / user / assistant message text.

The fix resolves attachments at the provider boundary (so every ``events``
reader gets usable content) and reads the ACP replay snapshot from the
resident, un-condensed window (so it never touches the provider at all).
"""

from inspect_ai._util.content import ContentText
from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL, resolve_events_attachments
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.transcript_history_provider import (
    BufferTranscriptHistoryProvider,
)
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


def _model_event(
    input_messages: list[ChatMessage],
    *,
    uuid: str | None = None,
    call: ModelCall | None = None,
) -> ModelEvent:
    return ModelEvent(
        uuid=uuid,
        model="mockllm/model",
        input=input_messages,
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "ok"),
        call=call,
    )


def test_resolve_events_attachments_resolves_message_content() -> None:
    attachments = {"h1": "SYSTEM PROMPT", "h2": "USER PROMPT"}
    event = _model_event(
        [
            ChatMessageSystem(content=f"{ATTACHMENT_PROTOCOL}h1"),
            ChatMessageUser(
                content=[
                    ContentText(text=f"{ATTACHMENT_PROTOCOL}h2"),
                    ContentText(text="plain tail"),
                ]
            ),
        ]
    )

    events: list[Event] = [event]
    [resolved] = resolve_events_attachments(events, attachments)

    assert isinstance(resolved, ModelEvent)
    assert resolved.input[0].content == "SYSTEM PROMPT"
    user_content = resolved.input[1].content
    assert isinstance(user_content, list)
    assert isinstance(user_content[0], ContentText)
    assert user_content[0].text == "USER PROMPT"
    assert isinstance(user_content[1], ContentText)
    assert user_content[1].text == "plain tail"
    # input event is not mutated in place
    assert event.input[0].content == f"{ATTACHMENT_PROTOCOL}h1"


def test_resolve_events_attachments_unknown_ref_passes_through() -> None:
    event = _model_event([ChatMessageUser(content=f"{ATTACHMENT_PROTOCOL}missing")])
    events: list[Event] = [event]
    [resolved] = resolve_events_attachments(events, {})
    # No matching attachment -> ref is left as-is rather than dropped.
    assert isinstance(resolved, ModelEvent)
    assert resolved.input[0].content == f"{ATTACHMENT_PROTOCOL}missing"


def test_resolve_events_attachments_core_vs_full_model_call() -> None:
    call = ModelCall.create(
        {"messages": [{"role": "user", "content": f"{ATTACHMENT_PROTOCOL}h1"}]}, None
    )
    event = _model_event([ChatMessageUser(content="hi")], call=call)
    events: list[Event] = [event]

    # "core" (default) leaves ModelEvent.call condensed, matching the resident
    # in-memory representation.
    [core] = resolve_events_attachments(events, {"h1": "BIG CALL"})
    assert isinstance(core, ModelEvent) and core.call is not None
    assert f"{ATTACHMENT_PROTOCOL}h1" in core.call.model_dump_json()
    assert "BIG CALL" not in core.call.model_dump_json()

    # "full" also resolves the model call payload.
    [full] = resolve_events_attachments(
        events, {"h1": "BIG CALL"}, resolve_attachments="full"
    )
    assert isinstance(full, ModelEvent) and full.call is not None
    assert "BIG CALL" in full.call.model_dump_json()


def test_resolve_events_attachments_false_is_noop() -> None:
    events: list[Event] = [
        _model_event([ChatMessageUser(content=f"{ATTACHMENT_PROTOCOL}h1")])
    ]
    result = resolve_events_attachments(events, {"h1": "X"}, resolve_attachments=False)
    assert result is events


def test_buffer_history_provider_resolves_attachments(tmp_path) -> None:
    # Long content (> the buffer's 100-char condense threshold) is extracted to
    # an attachment when written to the buffer DB.
    big_system = "SYS-" + "y" * 300
    big_user = "USER-" + "x" * 300
    event = _model_event(
        [
            ChatMessageSystem(id="sys-msg", content=big_system),
            ChatMessageUser(id="usr-msg", content=big_user),
        ],
        uuid="e1",
    )

    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events([SampleEvent(id="s", epoch=1, event=event)])
    provider = BufferTranscriptHistoryProvider(db, "s", 1)

    # events() resolves attachments back to the underlying content.
    [me] = [e for e in provider.events() if isinstance(e, ModelEvent)]
    assert me.input[0].content == big_system
    assert me.input[1].content == big_user
    assert ATTACHMENT_PROTOCOL not in me.model_dump_json()

    # iter_events() (the lazy/streaming path) resolves per-event too.
    [me_iter] = [e for e in provider.iter_events() if isinstance(e, ModelEvent)]
    assert me_iter.input[0].content == big_system
    assert me_iter.input[1].content == big_user
