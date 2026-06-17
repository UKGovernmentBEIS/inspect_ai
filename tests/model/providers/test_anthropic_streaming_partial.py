"""Offline (no-API) tests for the partial-output streaming flush path.

These pin down two behaviors that are hard to trigger reliably against the
live API:

  * pause_turn continuations (edge case C): the partial stream remains a
    monotone-growing prefix across continuations — head content stays
    visible while the tail streams in, because
    ``_perform_request_and_continuations`` threads the head's translated
    content into the tail's flush.

  * interleaved block ordering (edge case D): tool calls go to a separate
    ``tool_calls`` list, so their position relative to thinking/text blocks
    is not represented in the partial's ``content`` ordering.

They drive the real ``_perform_request_and_continuations`` with a fake
streaming client and a real active ``ModelEvent`` + ``Transcript`` so the
flush path (``update_active_model_event_output``) actually runs.
"""

from __future__ import annotations

import types
from typing import Any

from anthropic.types import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._samples import track_active_model_event
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.anthropic import (
    AnthropicAPI,
    _partial_output_from_snapshot,
)


def _make_message(content: list[Any], stop_reason: str) -> Message:
    return Message(
        id=f"msg_{stop_reason}_{id(content)}",
        type="message",
        role="assistant",
        model="claude-sonnet-4-6",
        stop_reason=stop_reason,  # type: ignore[arg-type]
        content=content,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


class _FakeStream:
    """Mimics anthropic AsyncMessageStream for _capture_compaction_from_stream.

    Yields a sequence of fake content_block_* events; current_message_snapshot
    grows as blocks are revealed, exactly as the real SDK accumulates.
    """

    def __init__(self, blocks: list[Any]) -> None:
        self._blocks = blocks
        # snapshot starts empty; revealed[] grows as we iterate
        self._revealed: list[Any] = []
        self._final = _make_message(blocks, stop_reason="pause_turn")

    @property
    def current_message_snapshot(self) -> Message:
        # snapshot reflects only blocks revealed so far during iteration
        return _make_message(list(self._revealed), stop_reason="pause_turn")

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __aiter__(self) -> "_FakeStream":
        self._idx = 0
        return self

    async def __anext__(self) -> Any:
        if self._idx >= len(self._blocks):
            # at end, snapshot is the full message
            self._revealed = list(self._blocks)
            raise StopAsyncIteration
        block = self._blocks[self._idx]
        self._idx += 1
        self._revealed.append(block)

        # a content_block_start-like event; the flush filter only checks
        # event.type and uses stream.current_message_snapshot, so a minimal
        # namespace object suffices.
        return types.SimpleNamespace(type="content_block_start", index=self._idx - 1)


def test_partial_output_block_ordering_loses_tool_position() -> None:
    """Edge case D: tool position relative to text/thinking is lost.

    The model emits thinking -> tool_use -> text. The partial puts thinking
    and text in `content` (in order) but the tool_use lands in the separate
    `tool_calls` list, so the rendered `content` is (reasoning, text) with no
    indication the tool call happened *between* them.
    """
    snapshot = _make_message(
        [
            ThinkingBlock(type="thinking", thinking="let me think", signature="sig"),
            ToolUseBlock(type="tool_use", id="t1", name="add", input={"x": 1}),
            TextBlock(type="text", text="done"),
        ],
        stop_reason="end_turn",
    )
    out = _partial_output_from_snapshot(snapshot, "claude-sonnet-4-6")
    content = out.message.content
    assert isinstance(content, list)
    types_seq = [type(c).__name__ for c in content]
    # tool call is NOT positioned between reasoning and text in `content`
    assert types_seq == ["ContentReasoning", "ContentText"], types_seq
    assert out.message.tool_calls and out.message.tool_calls[0].id == "t1"
    # there is no way to know from `content` ordering that the tool was called
    # between the thinking and the final text.


def test_partial_thinking_without_signature() -> None:
    """Edge case B: mid-stream ThinkingBlock has signature=None -> ok."""
    snapshot = _make_message(
        [ThinkingBlock(type="thinking", thinking="partial reasoning", signature="")],
        stop_reason="end_turn",
    )
    # the SDK leaves signature == "" (its construct default) until the
    # signature_delta arrives at the end; emulate the None case too.
    snapshot.content[0].signature = None  # type: ignore[union-attr]
    out = _partial_output_from_snapshot(snapshot, "claude-sonnet-4-6")
    cr = out.message.content[0]
    assert isinstance(cr, ContentReasoning)
    assert cr.reasoning == "partial reasoning"
    assert cr.signature is None


async def test_pause_turn_partial_output_monotone() -> None:
    """Edge case C: partial output stays monotone across a continuation.

    Drive ``_perform_request_and_continuations`` with two streamed messages:
      head: ``pause_turn``, text "HEAD"
      tail: ``end_turn``,   text "TAIL"

    Every partial flush onto the single active ``ModelEvent`` must keep
    "HEAD" once it appears — the tail's flush prepends the head's already-
    translated content so the live snapshot is a growing prefix of the
    final merged output, never a tail-only reset.
    """
    head_blocks = [TextBlock(type="text", text="HEAD")]
    tail_blocks = [TextBlock(type="text", text="TAIL")]

    head_stream = _FakeStream(head_blocks)
    head_stream._final = _make_message(head_blocks, stop_reason="pause_turn")
    tail_stream = _FakeStream(tail_blocks)
    tail_stream._final = _make_message(tail_blocks, stop_reason="end_turn")

    # the head stream must report pause_turn so a continuation fires; the
    # _FakeStream.current_message_snapshot hardcodes pause_turn which is fine
    # for the flush, but the FINAL message returned to model_output_from_message
    # is stream.current_message_snapshot after iteration. Patch that to carry
    # the right stop_reason per stream.
    head_stream.__class__.current_message_snapshot = property(  # type: ignore[assignment]
        lambda s: s._final
        if s._idx >= len(s._blocks)
        else _make_message(list(s._revealed), stop_reason="pause_turn")
    )

    streams = iter([head_stream, tail_stream])

    class _FakeMessages:
        def stream(self, **kwargs: Any) -> _FakeStream:
            return next(streams)

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    api = AnthropicAPI.__new__(AnthropicAPI)
    api._batcher = None  # type: ignore[attr-defined]
    api.client = _FakeClient()  # type: ignore[assignment]
    api.service_model_name = lambda: "claude-sonnet-4-6"  # type: ignore[method-assign]
    api.cache_diagnostics_enabled = lambda config: False  # type: ignore[method-assign]

    # active transcript + pending model event so the flush path runs
    transcript = Transcript()
    init_transcript(transcript)
    event = ModelEvent(
        model="claude-sonnet-4-6",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("claude-sonnet-4-6", ""),
        pending=True,
    )
    transcript._event(event)

    partial_texts: list[str] = []

    def on_event(ev: object) -> None:
        if isinstance(ev, ModelEvent) and ev.pending:
            content = ev.output.message.content
            if isinstance(content, list):
                txt = "".join(c.text for c in content if isinstance(c, ContentText))
            else:
                txt = content
            partial_texts.append(txt)

    transcript._subscribe(on_event)

    with track_active_model_event(event):
        _, output = await api._perform_request_and_continuations(
            request={"messages": []},
            streaming=True,
            tools=[],
            config=GenerateConfig(),
        )

    # final merged output is correct: HEAD + TAIL
    final_text = "".join(
        c.text for c in output.message.content if isinstance(c, ContentText)
    )
    assert "HEAD" in final_text and "TAIL" in final_text, final_text

    # the partial stream is monotone: HEAD appears, and once it does, every
    # subsequent partial still contains it; the tail partial is HEAD+TAIL.
    print("partial_texts:", partial_texts)
    assert any("HEAD" in t for t in partial_texts), (
        f"expected a HEAD partial; got {partial_texts}"
    )
    seen_head = False
    for t in partial_texts:
        if "HEAD" in t:
            seen_head = True
        assert not seen_head or "HEAD" in t, (
            f"partial dropped HEAD after it appeared (non-monotone): {partial_texts}"
        )
    assert any("HEAD" in t and "TAIL" in t for t in partial_texts), (
        f"expected a HEAD+TAIL partial during the tail stream; got {partial_texts}"
    )
