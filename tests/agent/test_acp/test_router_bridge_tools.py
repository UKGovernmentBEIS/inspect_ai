"""Live synthesis of tool-call cards for agent-bridge agents.

Bridged scaffolds (claude_code, codex, …) run their own tools, so no
``ToolEvent`` is ever emitted — the calls live only on the assistant message and
their results return as ``ChatMessageTool`` in a later call's input. The router
synthesizes ``ToolCallStart`` / ``ToolCallProgress`` cards from the
``ModelEvent`` stream, gated on ``in_bridge_model_generate()`` so the react path
(which has real ``ToolEvent``s) is left entirely untouched.

These drive the real ``_AcpEventRouter`` with synthetic events, wrapping the
bridged feeds in ``bridge_model_generate()`` so the synchronous subscriber sees
the same flag a live bridge generate would set.
"""

from acp.schema import (
    ContentToolCallContent,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

from inspect_ai.agent._acp.event_mapping import _AcpEventRouter
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.agent._bridge.util import bridge_model_generate
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_session() -> LiveAcpTransport:
    session = LiveAcpTransport()
    session._attachable_override = True
    return session


def _attach_router(
    session: LiveAcpTransport,
) -> tuple[_AcpEventRouter, list[SessionNotification]]:
    published: list[SessionNotification] = []
    session.publish = published.append  # type: ignore[method-assign,assignment]
    router = _AcpEventRouter(session)
    router.attach()
    return router, published


def _bash_call(
    tool_id: str = "tc1", command: str = "ls -la", *, with_view: bool = True
) -> ToolCall:
    view = (
        ToolCallContent(
            title="bash", format="markdown", content=f"```bash\n{command}\n```\n"
        )
        if with_view
        else None
    )
    return ToolCall(
        id=tool_id, function="bash", arguments={"command": command}, view=view
    )


def _tool_call_event(*calls: ToolCall) -> ModelEvent:
    """A completed bridged model turn whose assistant message holds *calls*."""
    message = ChatMessageAssistant(content="", tool_calls=list(calls))
    return ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model", choices=[ChatCompletionChoice(message=message)]
        ),
    )


def _result_event(*results: ChatMessageTool) -> ModelEvent:
    """A later bridged turn whose input carries the prior calls' *results*."""
    message = ChatMessageAssistant(content="done")
    return ModelEvent(
        model="mockllm/model",
        input=list(results),
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model", choices=[ChatCompletionChoice(message=message)]
        ),
    )


def _starts(published: list[SessionNotification]) -> list[ToolCallStart]:
    return [n.update for n in published if isinstance(n.update, ToolCallStart)]


def _progress(published: list[SessionNotification]) -> list[ToolCallProgress]:
    return [n.update for n in published if isinstance(n.update, ToolCallProgress)]


def _content_text(update: ToolCallStart | ToolCallProgress) -> str:
    assert update.content is not None
    parts: list[str] = []
    for block in update.content:
        if isinstance(block, ContentToolCallContent) and isinstance(
            block.content, TextContentBlock
        ):
            parts.append(block.content.text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bridge_model_event_synthesizes_in_progress_start() -> None:
    """A bridged tool call becomes an in-progress card carrying the view."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        with bridge_model_generate():
            tr._event(_tool_call_event(_bash_call()))
        starts = _starts(published)
        assert len(starts) == 1
        start = starts[0]
        assert start.tool_call_id == "tc1"
        assert start.status == "in_progress"
        # descriptive title from the args, not a bare "bash"
        assert start.title == "bash ls -la"
        # raw args always forwarded for the client's debug view
        assert start.raw_input == {"command": "ls -la"}
        # the scaffold-provided view renders richly (not args-only)
        assert "ls -la" in _content_text(start)
        assert "```bash" in _content_text(start)
    finally:
        _transcript.reset(token)


def test_bridge_tool_result_settles_completed() -> None:
    """The result in a later turn's input flips the card to completed."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        call = _bash_call(command="ls")
        with bridge_model_generate():
            tr._event(_tool_call_event(call))
            tr._event(
                _result_event(
                    ChatMessageTool(
                        tool_call_id="tc1", function="bash", content="total 0\nfile.txt"
                    )
                )
            )
        progress = _progress(published)
        assert len(progress) == 1
        upd = progress[0]
        assert upd.tool_call_id == "tc1"
        assert upd.status == "completed"
        text = _content_text(upd)
        # update REPLACES start content, so the view must be preserved...
        assert "ls" in text
        # ...alongside the (fenced) result
        assert "total 0" in text
    finally:
        _transcript.reset(token)


def test_bridge_tool_error_settles_failed() -> None:
    """A tool result carrying an error flips the card to failed."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        with bridge_model_generate():
            tr._event(_tool_call_event(_bash_call()))
            tr._event(
                _result_event(
                    ChatMessageTool(
                        tool_call_id="tc1",
                        function="bash",
                        content="boom",
                        error=ToolCallError(type="unknown", message="boom"),
                    )
                )
            )
        progress = _progress(published)
        assert len(progress) == 1
        assert progress[0].status == "failed"
    finally:
        _transcript.reset(token)


def test_result_settles_on_pending_phase_of_next_turn() -> None:
    """A pending (not yet completed) next turn already carries the result.

    The result is in the request the moment the next generation starts, so the
    card should flip to completed on the pending phase — no wait for the full
    round-trip.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        call = _bash_call(command="ls")
        with bridge_model_generate():
            tr._event(_tool_call_event(call))
            pending_next = ModelEvent(
                model="mockllm/model",
                input=[
                    ChatMessageTool(tool_call_id="tc1", function="bash", content="ok")
                ],
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(model="mockllm/model", choices=[]),
                pending=True,
            )
            tr._event(pending_next)
        progress = _progress(published)
        assert [p.status for p in progress] == ["completed"]
    finally:
        _transcript.reset(token)


def test_react_model_event_does_not_synthesize() -> None:
    """Without the bridge flag, a model event with tool_calls synthesizes nothing.

    react has real ``ToolEvent``s; its in-flight view must keep coming from
    those, never from a card the mapper invented (which would lack the view
    until completion).
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        # NOTE: no bridge_model_generate() wrapper — this is the react path
        tr._event(_tool_call_event(_bash_call()))
        assert _starts(published) == []
        assert _progress(published) == []
    finally:
        _transcript.reset(token)


def test_real_tool_event_after_synth_start_is_update_not_duplicate() -> None:
    """Mixed-bridge safety net: a real ToolEvent for a synth'd id is an update.

    If an Inspect tool somehow does emit a ``ToolEvent`` for a call we already
    synthesized a start for, the ``seen_tool_call_ids`` dedup routes it through
    the update branch — one card, not two.
    """
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        with bridge_model_generate():
            tr._event(_tool_call_event(_bash_call(command="ls")))
        # a real ToolEvent arrives for the same id
        tr._event(
            ToolEvent(
                id="tc1",
                function="bash",
                arguments={"command": "ls"},
                result="total 0",
            )
        )
        assert len(_starts(published)) == 1
        completed = [
            p
            for p in _progress(published)
            if p.tool_call_id == "tc1" and p.status == "completed"
        ]
        assert completed
    finally:
        _transcript.reset(token)


def test_bridge_text_only_turn_synthesizes_no_tool_cards() -> None:
    """A bridged turn with no tool calls emits assistant content but no cards."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        message = ChatMessageAssistant(content="just talking")
        event = ModelEvent(
            model="mockllm/model",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(
                model="mockllm/model", choices=[ChatCompletionChoice(message=message)]
            ),
        )
        with bridge_model_generate():
            tr._event(event)
        assert _starts(published) == []
        assert _progress(published) == []
    finally:
        _transcript.reset(token)


def test_bridge_start_without_view_falls_back_to_title() -> None:
    """A bridged call whose scaffold attached no view still gets a titled card."""
    tr = Transcript()
    token = _transcript.set(tr)
    try:
        _, published = _attach_router(_new_session())
        with bridge_model_generate():
            tr._event(_tool_call_event(_bash_call(command="whoami", with_view=False)))
        starts = _starts(published)
        assert len(starts) == 1
        assert starts[0].status == "in_progress"
        assert starts[0].title == "bash whoami"
        assert starts[0].content is None
    finally:
        _transcript.reset(token)
