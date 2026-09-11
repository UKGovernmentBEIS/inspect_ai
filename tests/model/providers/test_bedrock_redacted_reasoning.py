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
import json
from typing import Any, AsyncIterator

import pytest
from test_helpers.utils import skip_if_trio

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from botocore.exceptions import ParamValidationError  # noqa: E402

from inspect_ai._util.content import ContentReasoning, ContentText  # noqa: E402
from inspect_ai.model._chat_message import (  # noqa: E402
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
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
    converse_messages,
    converse_response_from_stream,
    model_output_from_response,
    redacted_content_bytes,
)
from inspect_ai.tool._tool_call import ToolCall  # noqa: E402

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


@pytest.mark.parametrize(
    "encoded",
    [
        pytest.param("not!valid!base64!", id="invalid-base64"),
        # a non-ASCII string raises a bare ValueError, not binascii.Error
        pytest.param("café==", id="non-ascii"),
        pytest.param("", id="empty"),
    ],
)
async def test_redacted_reasoning_with_unusable_bytes_is_dropped(
    encoded: str,
) -> None:
    """An unreadable or empty internal payload is dropped, never sent.

    `internal` is JsonValue read back from an eval log, so any string can
    turn up here; none of these may escape as an exception or as an empty
    `redactedContent` on the wire.
    """
    reasoning = ContentReasoning(
        reasoning="",
        redacted=True,
        internal={REDACTED_CONTENT_KEY: encoded},
    )

    blocks = await converse_contents([reasoning, ContentText(text="150")])

    assert [b.text for b in blocks] == ["150"]
    assert all(b.reasoningContent is None for b in blocks)


async def test_empty_reasoning_text_is_never_replayed() -> None:
    """An empty reasoningText.text must never reach the wire.

    It is the exact field the redacted-reasoning models reject, and an
    empty union block is invalid to botocore, so a non-redacted block with
    no text is dropped instead.
    """
    blocks = await converse_contents(
        [ContentReasoning(reasoning=""), ContentText(text="150")]
    )

    assert [b.text for b in blocks] == ["150"]
    assert all(b.reasoningContent is None for b in blocks)


async def test_redacted_only_message_gets_no_content_placeholder() -> None:
    """Dropping the sole block must not yield an empty content list.

    Converse rejects a message with no content blocks at all.
    """
    blocks = await converse_contents([ContentReasoning(reasoning="", redacted=True)])

    assert len(blocks) == 1
    assert blocks[0].text is not None
    assert blocks[0].reasoningContent is None


async def test_dropped_block_with_tool_calls_keeps_message_non_empty() -> None:
    """The tool-calling shape from the bug report must survive the drop.

    `converse_chat_message` filters the NO_CONTENT placeholder back out for
    assistant messages that carry tool calls, so this path relies on the
    toolUse blocks rather than the placeholder to stay non-empty.
    """
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="", redacted=True)],
        tool_calls=[ToolCall(id="t1", function="ls", arguments={})],
    )

    _, messages = await converse_messages([message])

    assert len(messages) == 1
    assert len(messages[0].content) > 0
    assert [c.toolUse.name for c in messages[0].content if c.toolUse] == ["ls"]
    assert all(c.reasoningContent is None for c in messages[0].content)


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

    A non-redacted block still emulates its text, but
    `reasoning_to_think_tag` would otherwise base64 whatever sits on
    `internal` into an attribute the model then reads.
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


# ------------------------------------------------------ the tagged union


def test_both_union_members_would_fail_validation() -> None:
    """`ReasoningContentBlock` is a tagged union, so both is never valid.

    Enforced on the way out by botocore rather than by the model, which also
    parses responses and must let an unrecognised shape through instead of
    raising. This pins the behaviour the replay path relies on.
    """
    with pytest.raises(ParamValidationError, match="Invalid number of parameters"):
        _validate_against_service_model(
            {
                "modelId": "m",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "reasoningContent": {
                                    "reasoningText": {"text": "t"},
                                    "redactedContent": REDACTED_BYTES,
                                }
                            }
                        ],
                    }
                ],
            }
        )


def _validate_against_service_model(request: dict[str, object]) -> None:
    """Validate a Converse request against botocore's own service model.

    Offline and credential-free: this is the same parameter validation
    botocore runs before signing, so it catches a request shape the SDK
    would reject without needing AWS access.
    """
    import botocore.session
    from botocore.validate import validate_parameters

    service = botocore.session.get_session().get_service_model("bedrock-runtime")
    input_shape = service.operation_model("Converse").input_shape
    assert input_shape is not None
    validate_parameters(request, input_shape)


@pytest.mark.parametrize(
    "reasoning",
    [
        pytest.param(
            ContentReasoning(
                reasoning="",
                redacted=True,
                internal={
                    REDACTED_CONTENT_KEY: base64.b64encode(REDACTED_BYTES).decode()
                },
            ),
            id="redacted",
        ),
        pytest.param(ContentReasoning(reasoning="thinking..."), id="plaintext"),
        pytest.param(
            ContentReasoning(reasoning="", redacted=True), id="redacted-no-bytes"
        ),
    ],
)
async def test_replayed_request_passes_botocore_validation(
    reasoning: ContentReasoning,
) -> None:
    """Every replayed reasoning shape must be one botocore accepts."""
    message = ChatMessageAssistant(content=[reasoning, ContentText(text="150")])

    _, messages = await converse_messages([message])

    _validate_against_service_model(
        {
            "modelId": "us.openai.gpt-5.6-sol",
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
    )


async def test_empty_reasoning_block_would_fail_validation() -> None:
    """Guards the helper above: an empty union block is genuinely invalid.

    Without this, `test_replayed_request_passes_botocore_validation` would
    still pass if the replay path silently emitted empty blocks.
    """
    with pytest.raises(ParamValidationError, match="Must set one of"):
        _validate_against_service_model(
            {
                "modelId": "m",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"reasoningContent": {}}],
                    }
                ],
            }
        )


# ------------------------------------------- full provider, binary blobs

# `redactedContent` is a blob in the service model, so an encrypted trace is
# not required to be ASCII (the GPT-5.6 family happens to return base64 text).
# Arbitrary bytes must not break the model-call log.
BINARY_REDACTED_BYTES = b"\x00\xff\xfersn_\x80\x81binary"


class _FakeClient:
    """Stands in for the aioboto3 bedrock-runtime client."""

    def __init__(self, response: dict[str, Any], events: list[dict[str, Any]]):
        self._response = response
        self._events = events
        self.converse_calls: list[dict[str, Any]] = []

    async def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.converse_calls.append(kwargs)
        return self._response

    async def converse_stream(self, **kwargs: Any) -> dict[str, Any]:
        self.converse_calls.append(kwargs)
        return {"stream": _stream(self._events)}


class _FakeSession:
    def __init__(self, client: _FakeClient):
        self._client = client

    def client(self, **kwargs: Any) -> Any:
        client = self._client

        class _CM:
            async def __aenter__(self) -> _FakeClient:
                return client

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _CM()


def _binary_response() -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"reasoningContent": {"redactedContent": BINARY_REDACTED_BYTES}},
                    {"text": "150"},
                ],
            }
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    }


def _binary_stream_events() -> list[dict[str, Any]]:
    return _stream_events(
        {"reasoningContent": {"redactedContent": BINARY_REDACTED_BYTES}}
    )


def _make_api(streaming: bool | None) -> tuple[Any, _FakeClient]:
    from inspect_ai.model._providers.bedrock import BedrockAPI

    api = BedrockAPI(model_name="us.openai.gpt-5.6-sol", base_url=None)
    client = _FakeClient(_binary_response(), _binary_stream_events())
    api.session = _FakeSession(client)  # type: ignore[assignment]
    api.streaming = streaming
    return api, client


@pytest.mark.parametrize("streaming", [False, True], ids=["non-streamed", "streamed"])
@skip_if_trio
async def test_generate_survives_binary_encrypted_reasoning(
    streaming: bool,
) -> None:
    """A binary redactedContent blob must not break generate() or its log.

    Recording the raw response runs it through utf-8 JSON serialization,
    which a non-ASCII blob fails. Covers both the Converse and
    ConverseStream paths.
    """
    api, _client = _make_api(streaming)

    result = await api.generate(
        input=[ChatMessageUser(content="Answer with just the number.")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
    )
    assert isinstance(result, tuple)
    output, model_call = result
    assert not isinstance(output, Exception), output

    # the log must be JSON-serializable, with the blob placeholdered
    json.dumps(model_call.response)
    reasoning_block = model_call.response["output"]["message"]["content"][0]
    assert reasoning_block["reasoningContent"]["redactedContent"] == "<bytes>"

    # ...and the real bytes must still be available for replay
    blocks = output.message.content
    assert isinstance(blocks, list)
    reasoning = [c for c in blocks if isinstance(c, ContentReasoning)]
    assert len(reasoning) == 1
    assert reasoning[0].redacted is True
    assert redacted_content_bytes(reasoning[0]) == BINARY_REDACTED_BYTES


@skip_if_trio
async def test_binary_reasoning_replays_verbatim_through_the_provider() -> None:
    """End to end: the blob generate() returned is what replay sends back."""
    api, client = _make_api(streaming=False)

    result = await api.generate(
        input=[ChatMessageUser(content="Answer with just the number.")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
    )
    assert isinstance(result, tuple)
    output, _ = result
    assert not isinstance(output, Exception), output

    await api.generate(
        input=[
            ChatMessageUser(content="Answer with just the number."),
            ChatMessageAssistant(content=output.message.content, model=output.model),
            ChatMessageUser(content="Now double it."),
        ],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
    )

    replayed = client.converse_calls[-1]["messages"][1]["content"][0]
    assert replayed["reasoningContent"]["redactedContent"] == BINARY_REDACTED_BYTES
    assert "reasoningText" not in replayed["reasoningContent"]
    _validate_against_service_model(
        {"modelId": "m", "messages": client.converse_calls[-1]["messages"]}
    )
