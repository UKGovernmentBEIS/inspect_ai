"""Tests for Bedrock Converse `redactedContent` reasoning blocks.

Regression test for a `ConverseResponse` pydantic validation crash: some
models on Bedrock (observed with OpenAI's GPT-5.6 family, e.g.
`us.openai.gpt-5.6-sol`, invoked via the native `bedrock/` Converse-API
provider) return a `reasoningContent` block shaped as
`{"redactedContent": <bytes>}` instead of `{"reasoningText": {"text": ...}}`.
`ConverseReasoningContent.reasoningText` was a required field, so any
response containing a redacted reasoning block failed pydantic validation
before `model_output_from_response` ever ran -- surfacing as an opaque
`ValidationError` on every request to an affected model, not merely an
occasional or malformed-input failure.

Confirmed against the real Converse API (`aws bedrock-runtime converse
--model-id us.openai.gpt-5.6-sol`): the model consistently returns
`redactedContent`, never plaintext `reasoningText`, so this is not a rare
edge case for that model family -- it made GPT-5.6 Sol/Terra/Luna entirely
unusable through this provider.
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai._util.content import ContentReasoning, ContentText  # noqa: E402
from inspect_ai.model._providers.bedrock import (  # noqa: E402
    ConverseMessage,
    ConverseMessageContent,
    ConverseMetrics,
    ConverseOutput,
    ConverseReasoningContent,
    ConverseReasoningText,
    ConverseResponse,
    ConverseUsage,
    model_output_from_response,
)


def _response(content: list[ConverseMessageContent]) -> ConverseResponse:
    return ConverseResponse(
        output=ConverseOutput(
            message=ConverseMessage(role="assistant", content=content)
        ),
        stopReason="end_turn",
        usage=ConverseUsage(inputTokens=1, outputTokens=1, totalTokens=2),
        metrics=ConverseMetrics(latencyMs=1),
    )


def test_redacted_reasoning_content_does_not_raise() -> None:
    """A redactedContent reasoning block must parse, not raise."""
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    redactedContent=b"opaque-encrypted-bytes"
                )
            ),
            ConverseMessageContent(text="ANSWER: yes"),
        ]
    )

    output = model_output_from_response("us.openai.gpt-5.6-sol", response, [])
    message_content = output.choices[0].message.content
    assert isinstance(message_content, list)

    reasoning_blocks = [c for c in message_content if isinstance(c, ContentReasoning)]
    assert len(reasoning_blocks) == 1
    assert reasoning_blocks[0].redacted is True
    assert reasoning_blocks[0].reasoning == ""

    text_blocks = [c for c in message_content if isinstance(c, ContentText)]
    assert text_blocks[0].text == "ANSWER: yes"


def test_plaintext_reasoning_text_still_works() -> None:
    """The existing reasoningText path (e.g. Claude models) is unaffected."""
    response = _response(
        [
            ConverseMessageContent(
                reasoningContent=ConverseReasoningContent(
                    reasoningText=ConverseReasoningText(
                        text="thinking...", signature="sig-123"
                    )
                )
            ),
            ConverseMessageContent(text="ANSWER: yes"),
        ]
    )

    output = model_output_from_response("us.anthropic.claude-sonnet-5", response, [])
    message_content = output.choices[0].message.content
    assert isinstance(message_content, list)

    reasoning_blocks = [c for c in message_content if isinstance(c, ContentReasoning)]
    assert len(reasoning_blocks) == 1
    assert reasoning_blocks[0].redacted is False
    assert reasoning_blocks[0].reasoning == "thinking..."
    assert reasoning_blocks[0].signature == "sig-123"
