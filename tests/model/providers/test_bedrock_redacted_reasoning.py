"""Tests for Bedrock Converse `redactedContent` reasoning blocks.

Some models return reasoning as an opaque, provider-encrypted blob --
`reasoningContent: {"redactedContent": <bytes>}` -- rather than plaintext
`reasoningContent: {"reasoningText": {"text": ...}}`. It is the only shape
OpenAI's GPT-5.6 family returns on Bedrock (verified against the live
Converse API for `us.openai.gpt-5.6-sol`, `-terra` and `-luna`, on any
prompt that actually requires reasoning).

Two failures followed from not modeling it, and these tests cover both:

1. `ConverseReasoningContent.reasoningText` was required, so the whole
   response failed pydantic validation before `model_output_from_response`
   ran -- an opaque `ValidationError` rather than an answer.

2. Once parsed, replay still had to work. Sending the block back as an
   empty `reasoningText` is rejected outright:

       ValidationException: This model doesn't support the
       reasoningContent.reasoningText.text field for assistant messages.
       Remove reasoningContent.reasoningText.text and try again.

   so the encrypted bytes have to round-trip verbatim, which means carrying
   them on `ContentReasoning.internal` between parse and replay. Omitting
   the block entirely is accepted by the API and is the fallback when no
   bytes are available.

See https://github.com/UKGovernmentBEIS/inspect_ai/issues/5217.
"""

from __future__ import annotations

import base64
from typing import AsyncIterator

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai._util.content import ContentReasoning, ContentText  # noqa: E402
from inspect_ai.model._providers.bedrock import (  # noqa: E402
    REDACTED_CONTENT_KEY,
    ConverseMessage,
    ConverseMessageContent,
    ConverseMetrics,
    ConverseOutput,
    ConverseReasoningContent,
    ConverseReasoningText,
    ConverseResponse,
    ConverseUsage,
    converse_contents,
    converse_response_from_stream,
    model_output_from_response,
)

# shaped like the real thing: the blob is ASCII base64-ish text carrying an
# "rsn_" prefix, delivered in a bytes field
REDACTED_BYTES = b"rsn_pUPh16to4VKYDgJAPymbEAIFeHpe5rt9QstioYggnXwbv1utOgLH"


def _response(content: list[ConverseMessageContent]) -> ConverseResponse:
    return ConverseResponse(
        output=ConverseOutput(
            message=ConverseMessage(role="assistant", content=content)
        ),
        stopReason="end_turn",
        usage=ConverseUsage(inputTokens=1, outputTokens=1, totalTokens=2),
        metrics=ConverseMetrics(latencyMs=1),
    )


def _reasoning_blocks(response: ConverseResponse) -> list[ContentReasoning]:
    output = model_output_from_response("test-model", response, [])
    content = output.choices[0].message.content
    assert isinstance(content, list)
    return [c for c in content if isinstance(c, ContentReasoning)]


# --------------------------------------------------------------- parsing


def test_redacted_reasoning_parses_and_keeps_the_bytes() -> None:
    """A redactedContent block parses, and preserves the blob for replay."""
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    redactedContent=REDACTED_BYTES
                )
            ),
            ConverseMessageContent(text="150"),
        ]
    )

    blocks = _reasoning_blocks(response)
    assert len(blocks) == 1
    assert blocks[0].redacted is True
    assert blocks[0].reasoning == ""
    # the bytes survive, base64'd, so replay can send them back verbatim
    assert blocks[0].internal == {
        REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()
    }


def test_plaintext_reasoning_parses_unchanged() -> None:
    """The plaintext reasoningText path is untouched."""
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    reasoningText=ConverseReasoningText(text="thinking...")
                )
            ),
            ConverseMessageContent(text="150"),
        ]
    )

    blocks = _reasoning_blocks(response)
    assert len(blocks) == 1
    assert blocks[0].redacted is False
    assert blocks[0].reasoning == "thinking..."
    assert blocks[0].internal is None


def test_reasoning_with_both_text_and_redacted_content() -> None:
    """The API documents the two fields as co-occurring, not exclusive.

    Neither half may be dropped: the text is the visible reasoning, the
    bytes are needed for replay.
    """
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    reasoningText=ConverseReasoningText(text="visible part"),
                    redactedContent=REDACTED_BYTES,
                )
            ),
        ]
    )

    blocks = _reasoning_blocks(response)
    assert len(blocks) == 1
    assert blocks[0].reasoning == "visible part"
    # plaintext is present, so the block as a whole isn't redacted
    assert blocks[0].redacted is False
    assert blocks[0].internal == {
        REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()
    }


def test_empty_reasoning_content_does_not_raise() -> None:
    """An unmodeled reasoningContent shape is recorded, not raised on.

    Crashing on an unrecognised reasoning shape is the original bug; a
    signature-only block must not resurrect it.
    """
    response = _response(
        [ConverseMessageContent(reasoningContent=ConverseReasoningContent())]
    )

    blocks = _reasoning_blocks(response)
    assert len(blocks) == 1
    assert blocks[0].redacted is True
    assert blocks[0].internal is None


def test_unexpected_content_block_still_raises() -> None:
    """A content block with no recognised field at all is still an error."""
    with pytest.raises(ValueError, match="Unexpected message response"):
        model_output_from_response(
            "test-model", _response([ConverseMessageContent()]), []
        )


# ---------------------------------------------------------------- replay


async def test_redacted_reasoning_round_trips_verbatim() -> None:
    """Replay must send the encrypted bytes back, byte for byte."""
    reasoning = ContentReasoning(
        reasoning="",
        redacted=True,
        internal={REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()},
    )

    blocks = await converse_contents([reasoning, ContentText(text="150")])

    assert blocks[0].reasoningContent is not None
    assert blocks[0].reasoningContent.redactedContent == REDACTED_BYTES
    # crucially NOT an empty reasoningText, which the API rejects
    assert blocks[0].reasoningContent.reasoningText is None
    assert blocks[1].text == "150"


async def test_parse_then_replay_preserves_the_blob() -> None:
    """The full response -> ContentReasoning -> request round trip."""
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    redactedContent=REDACTED_BYTES
                )
            ),
            ConverseMessageContent(text="150"),
        ]
    )
    output = model_output_from_response("test-model", response, [])
    content = output.choices[0].message.content
    assert isinstance(content, list)

    blocks = await converse_contents(content)

    assert blocks[0].reasoningContent is not None
    assert blocks[0].reasoningContent.redactedContent == REDACTED_BYTES


async def test_redacted_reasoning_without_bytes_is_dropped() -> None:
    """With no recoverable bytes the block is omitted, not faked.

    Reasoning captured from another provider, or read from a log written
    before the bytes were preserved, has nothing valid to send. The API
    accepts the block's absence but rejects a substitute empty
    reasoningText, so dropping it is the only way the turn survives.
    """
    reasoning = ContentReasoning(reasoning="", redacted=True)

    blocks = await converse_contents([reasoning, ContentText(text="150")])

    assert [b.text for b in blocks] == ["150"]
    assert all(b.reasoningContent is None for b in blocks)


async def test_redacted_reasoning_with_corrupt_bytes_is_dropped() -> None:
    """An unreadable internal payload is dropped rather than sent."""
    reasoning = ContentReasoning(
        reasoning="",
        redacted=True,
        internal={REDACTED_CONTENT_KEY: "not!valid!base64!"},
    )

    blocks = await converse_contents([reasoning, ContentText(text="150")])

    assert [b.text for b in blocks] == ["150"]


async def test_redacted_only_message_gets_no_content_placeholder() -> None:
    """Dropping the sole block must not yield an empty content list.

    Converse rejects a message with no content blocks at all.
    """
    blocks = await converse_contents([ContentReasoning(reasoning="", redacted=True)])

    assert len(blocks) == 1
    assert blocks[0].text is not None
    assert blocks[0].reasoningContent is None


async def test_both_halves_round_trip_together() -> None:
    """A block carrying text and bytes replays both."""
    reasoning = ContentReasoning(
        reasoning="visible part",
        redacted=False,
        internal={REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()},
    )

    blocks = await converse_contents([reasoning])

    assert blocks[0].reasoningContent is not None
    assert blocks[0].reasoningContent.reasoningText is not None
    assert blocks[0].reasoningContent.reasoningText.text == "visible part"
    assert blocks[0].reasoningContent.redactedContent == REDACTED_BYTES


async def test_plaintext_reasoning_replay_unchanged() -> None:
    """Plaintext reasoning still replays as a bare reasoningText."""
    blocks = await converse_contents([ContentReasoning(reasoning="thinking...")])

    assert blocks[0].reasoningContent is not None
    assert blocks[0].reasoningContent.reasoningText is not None
    assert blocks[0].reasoningContent.reasoningText.text == "thinking..."
    assert blocks[0].reasoningContent.redactedContent is None


async def test_redacted_reasoning_skipped_under_emulation() -> None:
    """Under think-tag emulation a redacted block is skipped entirely.

    It has no plaintext to emulate -- only opaque protocol state, which
    `reasoning_to_think_tag` would otherwise encode into base64 attributes
    on an empty <think> tag and send to the model as prompt text.
    """
    reasoning = ContentReasoning(
        reasoning="",
        redacted=True,
        internal={REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()},
    )

    blocks = await converse_contents(
        [reasoning, ContentText(text="150")], emulate_reasoning=True
    )

    assert [b.text for b in blocks] == ["150"]


async def test_plaintext_reasoning_still_emulated() -> None:
    """Plaintext reasoning is still rendered as a <think> tag."""
    blocks = await converse_contents(
        [ContentReasoning(reasoning="thinking...")], emulate_reasoning=True
    )

    assert blocks[0].text is not None
    assert "<think" in blocks[0].text
    assert "thinking..." in blocks[0].text


async def test_emulated_think_tag_omits_the_redacted_carrier() -> None:
    """The bytes carrier must never reach the model as prompt text.

    A block with both plaintext and redacted halves still emulates its
    text, but `reasoning_to_think_tag` would otherwise base64 the carrier
    into an `internal="..."` attribute the model then reads.
    """
    encoded = base64.b64encode(REDACTED_BYTES).decode()
    reasoning = ContentReasoning(
        reasoning="visible part",
        redacted=False,
        internal={REDACTED_CONTENT_KEY: encoded},
    )

    blocks = await converse_contents([reasoning], emulate_reasoning=True)

    assert blocks[0].text is not None
    assert "visible part" in blocks[0].text
    assert "internal=" not in blocks[0].text
    assert encoded not in blocks[0].text


# --------------------------------------------------------------- streaming


async def _stream(
    events: list[dict[str, object]],
) -> AsyncIterator[dict[str, object]]:
    for event in events:
        yield event


def _stream_events(delta: dict[str, object]) -> list[dict[str, object]]:
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": delta}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": "150"}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        },
    ]


async def test_streamed_redacted_reasoning_is_preserved() -> None:
    """Redacted deltas must not vanish when streaming is on."""
    events = _stream_events({"reasoningContent": {"redactedContent": REDACTED_BYTES}})

    response = await converse_response_from_stream(_stream(events))

    content = response.output.message.content
    assert content[0].reasoningContent is not None
    assert content[0].reasoningContent.redactedContent == REDACTED_BYTES
    assert content[1].text == "150"


async def test_streamed_redacted_reasoning_matches_non_streaming() -> None:
    """The streamed and non-streamed paths must agree on the parsed output."""
    events = _stream_events({"reasoningContent": {"redactedContent": REDACTED_BYTES}})
    streamed = await converse_response_from_stream(_stream(events))

    non_streamed = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    redactedContent=REDACTED_BYTES
                )
            ),
            ConverseMessageContent(text="150"),
        ]
    )

    assert _reasoning_blocks(streamed) == _reasoning_blocks(non_streamed)


async def test_streamed_redacted_reasoning_accumulates_across_deltas() -> None:
    """A blob split across deltas is joined in order."""
    events: list[dict[str, object]] = [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"redactedContent": b"rsn_first"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"redactedContent": b"-second"}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        },
    ]

    response = await converse_response_from_stream(_stream(events))

    content = response.output.message.content
    assert content[0].reasoningContent is not None
    assert content[0].reasoningContent.redactedContent == b"rsn_first-second"
