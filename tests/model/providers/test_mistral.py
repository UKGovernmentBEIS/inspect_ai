import logging
from typing import Any

import pytest
from test_helpers.utils import skip_if_no_mistral, skip_if_no_mistral_package

from inspect_ai._util.content import ContentImage
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.tool import (
    ToolInfo,
    ToolParam,
    ToolParams,
)


@pytest.fixture
def tiktok_tool_with_description_param():
    """Fixture that provides a tool with a parameter named 'description'.

    This tool is specifically designed to test handling of parameters named 'description',
    which previously caused issues with the Mistral API.
    """
    return ToolInfo(
        name="upload_tiktok_video",
        description="Upload a video to TikTok with description and tags.",
        parameters=ToolParams(
            type="object",
            properties={
                "video_path": ToolParam(
                    type="string",
                    description="The file path of the video to be uploaded",
                ),
                "description": ToolParam(
                    type="string",
                    description="The description for the TikTok video",
                ),
            },
            required=["video_path", "description"],
        ),
    )


@skip_if_no_mistral_package
def test_mistral_tool_schema_formatting(tiktok_tool_with_description_param):
    """Test that the tool schema is correctly formatted for the Mistral API.

    This test verifies that our tool schema conversion correctly includes the outer schema
    structure with type, properties, and required fields that Mistral expects.
    """
    from inspect_ai.model._providers.mistral import mistral_chat_tools

    # Convert the tool to Mistral format
    mistral_tools = mistral_chat_tools([tiktok_tool_with_description_param])

    # Verify the structure
    assert len(mistral_tools) == 1
    mistral_tool = mistral_tools[0]

    # Check that the tool has the correct type
    assert mistral_tool.type == "function"

    # Check that the function has the correct name and description
    assert mistral_tool.function.name == "upload_tiktok_video"
    assert (
        mistral_tool.function.description
        == "Upload a video to TikTok with description and tags."
    )

    # Check that the parameters have the correct structure
    params = mistral_tool.function.parameters
    assert params["type"] == "object"
    assert "properties" in params
    assert "required" in params
    assert params["required"] == ["video_path", "description"]

    # Check that the properties have the correct structure
    properties = params["properties"]
    assert "video_path" in properties
    assert "description" in properties
    assert properties["video_path"]["type"] == "string"
    assert properties["description"]["type"] == "string"


@pytest.mark.anyio
@skip_if_no_mistral
@skip_if_no_mistral_package
async def test_mistral_with_description_parameter(tiktok_tool_with_description_param):
    """Test that the Mistral API correctly accepts a tool with a parameter named 'description'.

    This test verifies that our fix for the tool schema formatting works correctly
    when calling the actual Mistral API.
    """
    model = get_model(
        "mistral/mistral-small-latest",
        config=GenerateConfig(
            temperature=0.0,
        ),
    )

    # Create a simple prompt
    messages = [
        ChatMessageUser(content="Hello, can you help me upload a video to TikTok?")
    ]

    # Use the tool with a parameter named 'description'
    tools = [tiktok_tool_with_description_param]

    try:
        # This should no longer raise an error with our fix
        result = await model.generate(messages, tools=tools)
        # If we get here, the test passed
        assert result is not None, "Expected a result from the model"
    except Exception as e:
        pytest.fail(f"Test failed with exception: {e}")


@skip_if_no_mistral_package
async def test_completion_content_chunks_image_url_string():
    """Test that ImageURLChunk with string URL converts to ContentImage."""
    from mistralai.client.models import ImageURLChunk

    from inspect_ai.model._providers.mistral import completion_content_chunks

    image = "data:image/png;base64,iVBORw0KGgo="
    chunk = ImageURLChunk(image_url=image)
    result = await completion_content_chunks(chunk)
    assert len(result) == 1
    assert isinstance(result[0], ContentImage)
    assert result[0].image == image


@skip_if_no_mistral_package
async def test_completion_content_chunks_image_url_object():
    """Test that ImageURLChunk with ImageURL object converts to ContentImage with detail."""
    from unittest.mock import AsyncMock, patch

    from mistralai.client.models import ImageURL, ImageURLChunk

    from inspect_ai.model._providers.mistral import completion_content_chunks

    url = "https://example.com/img.png"
    image = "data:image/png;base64,iVBORw0KGgo="
    chunk = ImageURLChunk(image_url=ImageURL(url=url, detail="high"))
    with patch(
        "inspect_ai.model._providers.mistral.provider_image_data_uri",
        new=AsyncMock(return_value=image),
    ) as materialize:
        result = await completion_content_chunks(chunk)

    materialize.assert_awaited_once_with(url)
    assert len(result) == 1
    assert isinstance(result[0], ContentImage)
    assert result[0].image == image
    assert result[0].detail == "high"


@skip_if_no_mistral_package
async def test_mistral_output_url_is_materialized_before_replay():
    from unittest.mock import AsyncMock, patch

    from mistralai.client.models import ImageURL, ImageURLChunk

    from inspect_ai.model._providers.mistral import (
        completion_content_chunks,
        mistral_content_chunk,
    )

    url = "https://example.com/img.png"
    image = "data:image/png;base64,iVBORw0KGgo="
    chunk = ImageURLChunk(image_url=ImageURL(url=url, detail="high"))
    with patch(
        "inspect_ai.model._providers.mistral.provider_image_data_uri",
        new=AsyncMock(return_value=image),
    ) as materialize:
        content = (await completion_content_chunks(chunk))[0]

    replayed = await mistral_content_chunk(content)

    materialize.assert_awaited_once_with(url)
    assert isinstance(content, ContentImage)
    assert content.image == image
    assert replayed.image_url.url == image


@skip_if_no_mistral_package
async def test_mistral_conversation_output_url_is_materialized():
    from unittest.mock import AsyncMock, patch

    from mistralai.client.models import ImageURL, ImageURLChunk

    from inspect_ai.model._providers.mistral_conversation import (
        content_from_mistral_content_chunk,
    )

    url = "https://example.com/img.png"
    image = "data:image/png;base64,iVBORw0KGgo="
    chunk = ImageURLChunk(image_url=ImageURL(url=url, detail="low"))
    with patch(
        "inspect_ai.model._providers.mistral_conversation.provider_image_data_uri",
        new=AsyncMock(return_value=image),
    ) as materialize:
        content = await content_from_mistral_content_chunk(chunk)

    materialize.assert_awaited_once_with(url)
    assert isinstance(content, ContentImage)
    assert content.image == image
    assert content.detail == "low"


@skip_if_no_mistral_package
async def test_mistral_chat_forwards_config_extra_headers() -> None:
    """config.extra_headers must reach the chat completions request.

    The conversation-api path already merges them; this covers the chat path.
    """
    from unittest import mock
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from inspect_ai.model._providers.mistral import MistralAPI
    from inspect_ai.model._providers.util.hooks import HttpxHooks

    api = MistralAPI(
        model_name="mistral/mistral-small-latest",
        api_key="test-key",
        conversation_api=False,
    )

    captured: dict[str, object] = {}

    async def _capture(**kwargs: object) -> object:
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.sdk_configuration.async_client = httpx.AsyncClient()
    client.chat.complete_async = AsyncMock(side_effect=_capture)

    with mock.patch("inspect_ai.model._providers.mistral.Mistral", return_value=client):
        with pytest.raises(RuntimeError, match="stop after capture"):
            await api.generate(
                input=[ChatMessageUser(content="hi")],
                tools=[],
                tool_choice="none",
                config=GenerateConfig(
                    extra_headers={"x-custom-header": "custom-value"}
                ),
            )

    http_headers = captured["http_headers"]
    assert isinstance(http_headers, dict)
    assert http_headers["x-custom-header"] == "custom-value"
    assert HttpxHooks.REQUEST_ID_HEADER in http_headers


@skip_if_no_mistral_package
def test_mistral_reasoning_effort_mapping() -> None:
    """Mistral accepts only "high"/"none" — other Inspect values map to "high"."""
    from inspect_ai.model._providers.mistral_conversation import (
        mistral_reasoning_effort,
    )

    assert mistral_reasoning_effort("none") == "none"
    for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
        assert mistral_reasoning_effort(effort) == "high"


@skip_if_no_mistral_package
async def test_mistral_chat_forwards_reasoning_effort() -> None:
    """config.reasoning_effort must reach the chat completions request (mapped)."""
    from unittest import mock
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from inspect_ai.model._providers.mistral import MistralAPI

    api = MistralAPI(
        model_name="mistral/mistral-medium-latest",
        api_key="test-key",
        conversation_api=False,
    )

    async def request_effort(config: GenerateConfig) -> object:
        captured: dict[str, object] = {}

        async def _capture(**kwargs: object) -> object:
            captured.update(kwargs)
            raise RuntimeError("stop after capture")

        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.sdk_configuration.async_client = httpx.AsyncClient()
        client.chat.complete_async = AsyncMock(side_effect=_capture)

        with mock.patch(
            "inspect_ai.model._providers.mistral.Mistral", return_value=client
        ):
            with pytest.raises(RuntimeError, match="stop after capture"):
                await api.generate(
                    input=[ChatMessageUser(content="hi")],
                    tools=[],
                    tool_choice="none",
                    config=config,
                )
        return captured.get("reasoning_effort", "OMITTED")

    assert await request_effort(GenerateConfig(reasoning_effort="low")) == "high"
    assert await request_effort(GenerateConfig(reasoning_effort="none")) == "none"
    assert await request_effort(GenerateConfig()) == "OMITTED"


# -- Streaming (on_stream) ------------------------------------------------------


class _StreamCollector:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, event: Any) -> None:
        self.events.append(event)


@skip_if_no_mistral_package
def test_mistral_resolve_streaming_honors_on_stream() -> None:
    """Unset streaming is "auto": stream iff the caller passed on_stream."""
    from inspect_ai.model import ResponseSchema
    from inspect_ai.model._providers.mistral import MistralAPI
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer
    from inspect_ai.util._json import JSONSchema

    def _api(**kwargs: Any) -> MistralAPI:
        return MistralAPI(model_name="mistral-large-latest", api_key="test", **kwargs)

    config = GenerateConfig()
    collector = _StreamCollector()

    api = _api()
    assert api.streaming is None
    assert api.resolve_streaming(config) is False
    with model_stream_observer(ModelStreamObserver("test", collector)):
        assert api.resolve_streaming(config) is True

        # auto mode declines requests carrying a response_schema
        schema_config = GenerateConfig(
            response_schema=ResponseSchema(
                name="schema", json_schema=JSONSchema(type="object")
            )
        )
        assert api.resolve_streaming(schema_config) is False
        assert _api(streaming=True).resolve_streaming(schema_config) is True

        # explicit opt-out wins over an on_stream callback
        assert _api(streaming=False).resolve_streaming(config) is False

    # explicit opt-in streams without a callback
    assert _api(streaming=True).resolve_streaming(config) is True

    # -M args are YAML-parsed so "auto" arrives as a string; a typo'd value
    # raises rather than silently forcing streaming on or off
    assert _api(streaming="auto").streaming is None
    with pytest.raises(ValueError, match="streaming"):
        _api(streaming="always")


@skip_if_no_mistral_package
async def test_mistral_completion_from_stream() -> None:
    """The stream accumulator reconstructs the completion and reports deltas."""
    from mistralai.client.models import (
        CompletionChunk,
        CompletionEvent,
        CompletionResponseStreamChoice,
        DeltaMessage,
        FunctionCall,
        TextChunk,
        ThinkChunk,
        ToolCall,
        UsageInfo,
    )

    from inspect_ai.model._providers.mistral import mistral_completion_from_stream
    from inspect_ai.model._stream import (
        ModelStreamObserver,
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        model_stream_observer,
    )

    def _chunk(
        choices: list[CompletionResponseStreamChoice],
        usage: UsageInfo | None = None,
    ) -> CompletionEvent:
        return CompletionEvent(
            data=CompletionChunk(
                id="cmpl-1",
                model="mistral-large-latest",
                created=123,
                choices=choices,
                usage=usage,
            )
        )

    events = [
        # reasoning arrives as ThinkChunk content pieces
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(
                        role="assistant",
                        content=[ThinkChunk(thinking=[TextChunk(text="hmm")])],
                    ),
                    finish_reason=None,
                )
            ]
        ),
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0, delta=DeltaMessage(content="hel"), finish_reason=None
                )
            ]
        ),
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(
                        tool_calls=[
                            ToolCall(
                                id="call_1",
                                index=0,
                                function=FunctionCall(name="bash", arguments="{"),
                            )
                        ]
                    ),
                    finish_reason=None,
                )
            ]
        ),
        # continuation fragment for the same tool call index
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(
                        tool_calls=[
                            ToolCall(
                                index=0,
                                function=FunctionCall(
                                    name="", arguments='"cmd": "ls"}'
                                ),
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                )
            ]
        ),
        # final chunk carries usage
        _chunk(
            [], usage=UsageInfo(prompt_tokens=3, completion_tokens=7, total_tokens=10)
        ),
    ]

    async def _events() -> Any:
        for event in events:
            yield event

    collector = _StreamCollector()
    with model_stream_observer(ModelStreamObserver("test", collector)):
        completion = await mistral_completion_from_stream(_events())

    # final completion accumulated from the chunks
    choice = completion.choices[0]
    assert choice.finish_reason == "tool_calls"
    message = choice.message
    assert message is not None
    content = message.content
    assert isinstance(content, list)
    assert isinstance(content[0], ThinkChunk)
    think_text = content[0].thinking[0]
    assert isinstance(think_text, TextChunk) and think_text.text == "hmm"
    assert isinstance(content[1], TextChunk)
    assert content[1].text == "hel"
    tool_calls = message.tool_calls
    assert isinstance(tool_calls, list) and tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "bash"
    assert tool_calls[0].function.arguments == '{"cmd": "ls"}'
    assert completion.usage.total_tokens == 10

    # deltas were reported to on_stream (with tool fragments attributed)
    assert [type(e) for e in collector.events] == [
        StreamReasoningEvent,
        StreamTextEvent,
        StreamToolCallEvent,
        StreamToolCallEvent,
    ]
    assert collector.events[0].reasoning == "hmm"
    assert collector.events[1].text == "hel"
    assert collector.events[3].id == "call_1"
    assert collector.events[3].function == "bash"
    assert collector.events[3].arguments == '"cmd": "ls"}'


@skip_if_no_mistral_package
async def test_mistral_stream_gated_without_on_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an on_stream consumer only usage/heartbeat progress runs.

    Explicit streaming=true callers stream without asking for stream events,
    so delta construction (on_stream support code) must not run for them.
    """
    from mistralai.client.models import (
        CompletionChunk,
        CompletionEvent,
        CompletionResponseStreamChoice,
        DeltaMessage,
        UsageInfo,
    )

    import inspect_ai.model._providers.mistral as mistral_module
    from inspect_ai.model._providers.mistral import mistral_completion_from_stream
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    async def fail(delta: Any) -> None:
        raise AssertionError("delta reported without an on_stream consumer")

    monkeypatch.setattr(mistral_module, "report_model_stream_delta", fail)

    def _chunk(
        choices: list[CompletionResponseStreamChoice],
        usage: UsageInfo | None = None,
    ) -> CompletionEvent:
        return CompletionEvent(
            data=CompletionChunk(
                id="cmpl-1",
                model="mistral-large-latest",
                created=123,
                choices=choices,
                usage=usage,
            )
        )

    events = [
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0,
                    delta=DeltaMessage(role="assistant", content="hel"),
                    finish_reason=None,
                )
            ]
        ),
        _chunk(
            [
                CompletionResponseStreamChoice(
                    index=0, delta=DeltaMessage(content="lo"), finish_reason="stop"
                )
            ]
        ),
        _chunk(
            [], usage=UsageInfo(prompt_tokens=3, completion_tokens=7, total_tokens=10)
        ),
    ]

    async def _events() -> Any:
        for event in events:
            yield event

    observer = ModelStreamObserver("test", None)
    with model_stream_observer(observer):
        completion = await mistral_completion_from_stream(_events())

    # response assembly and the usage progress channel are unaffected
    message = completion.choices[0].message
    assert message is not None and message.content == "hello"
    assert observer._tokens_current == 7


@skip_if_no_mistral_package
async def test_mistral_stream_parallel_tool_calls_without_index() -> None:
    """Parallel calls with no server index don't collapse into one slot.

    The SDK defaults an absent index to 0, so slotting must not trust the
    default: each id-bearing fragment starts a new call.
    """
    from mistralai.client.models import (
        CompletionChunk,
        CompletionEvent,
        CompletionResponseStreamChoice,
        DeltaMessage,
        FunctionCall,
        ToolCall,
    )

    from inspect_ai.model._providers.mistral import mistral_completion_from_stream

    async def _events() -> Any:
        yield CompletionEvent(
            data=CompletionChunk(
                id="cmpl-1",
                model="mistral-large-latest",
                choices=[
                    CompletionResponseStreamChoice(
                        index=0,
                        delta=DeltaMessage(
                            tool_calls=[
                                ToolCall(
                                    id="call_a",
                                    function=FunctionCall(
                                        name="bash", arguments='{"a": 1}'
                                    ),
                                ),
                                ToolCall(
                                    id="call_b",
                                    function=FunctionCall(
                                        name="python", arguments='{"b": 2}'
                                    ),
                                ),
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ],
            )
        )

    completion = await mistral_completion_from_stream(_events())
    message = completion.choices[0].message
    assert message is not None
    tool_calls = message.tool_calls
    assert isinstance(tool_calls, list) and len(tool_calls) == 2
    assert tool_calls[0].id == "call_a"
    assert tool_calls[0].function.arguments == '{"a": 1}'
    assert tool_calls[1].id == "call_b"
    assert tool_calls[1].function.arguments == '{"b": 2}'


@skip_if_no_mistral_package
async def test_mistral_completion_from_stream_text_only() -> None:
    """All-string fragments join into plain string content."""
    from mistralai.client.models import (
        CompletionChunk,
        CompletionEvent,
        CompletionResponseStreamChoice,
        DeltaMessage,
    )

    from inspect_ai.model._providers.mistral import mistral_completion_from_stream

    async def _events() -> Any:
        fragments: list[tuple[str, Any]] = [("hel", None), ("lo", "stop")]
        for text, finish in fragments:
            yield CompletionEvent(
                data=CompletionChunk(
                    id="cmpl-1",
                    model="mistral-large-latest",
                    choices=[
                        CompletionResponseStreamChoice(
                            index=0,
                            delta=DeltaMessage(content=text),
                            finish_reason=finish,
                        )
                    ],
                )
            )

    completion = await mistral_completion_from_stream(_events())
    message = completion.choices[0].message
    assert message is not None and message.content == "hello"
    assert completion.choices[0].finish_reason == "stop"


@skip_if_no_mistral_package
async def test_mistral_completion_from_stream_missing_usage_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stream ending without usage warns rather than under-counting silently."""
    from mistralai.client.models import (
        CompletionChunk,
        CompletionEvent,
        CompletionResponseStreamChoice,
        DeltaMessage,
    )

    from inspect_ai.model._providers.mistral import mistral_completion_from_stream

    async def _events() -> Any:
        yield CompletionEvent(
            data=CompletionChunk(
                # unique model name: warn_once dedupes on message text
                # process-wide, and other stream tests also omit usage
                id="cmpl-1",
                model="mistral-missing-usage-test",
                choices=[
                    CompletionResponseStreamChoice(
                        index=0,
                        delta=DeltaMessage(content="hi"),
                        finish_reason="stop",
                    )
                ],
            )
        )

    with caplog.at_level(logging.WARNING, logger="inspect_ai.model._providers.mistral"):
        completion = await mistral_completion_from_stream(_events())
    assert completion.usage.total_tokens == 0
    assert any(
        "reported no token usage for a streamed response" in record.message
        for record in caplog.records
    )


@skip_if_no_mistral_package
async def test_mistral_streaming_true_warns_on_conversation_api(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An explicit streaming=true is ignored by the Conversation API — warn."""
    from inspect_ai.model import ModelOutput
    from inspect_ai.model._providers import mistral as mistral_provider

    async def _conversation_generate(**kwargs: Any) -> ModelOutput:
        return ModelOutput.from_content(
            model="mistral-conversation-warn-test", content="hi"
        )

    monkeypatch.setattr(
        mistral_provider, "mistral_conversation_generate", _conversation_generate
    )
    api = mistral_provider.MistralAPI(
        # unique model name: warn_once dedupes on message text process-wide
        model_name="mistral-conversation-warn-test",
        api_key="test",
        conversation_api=True,
        streaming=True,
    )
    with caplog.at_level(logging.WARNING, logger="inspect_ai.model._providers.mistral"):
        await api.generate(
            [ChatMessageUser(content="hi")], [], "auto", GenerateConfig()
        )
    assert any(
        "no effect on the Conversation API" in record.message
        for record in caplog.records
    )


@skip_if_no_mistral_package
async def test_mistral_completion_from_stream_empty() -> None:
    from inspect_ai.model._providers.mistral import mistral_completion_from_stream

    async def _events() -> Any:
        return
        yield

    with pytest.raises(RuntimeError, match="without delivering any chunks"):
        await mistral_completion_from_stream(_events())


@skip_if_no_mistral
async def test_mistral_stream_end_to_end() -> None:
    """Passing on_stream alone enables streaming on the chat-completions path."""
    from inspect_ai.model._stream import StreamTextEvent

    events: list[Any] = []

    async def collect(event: Any) -> None:
        events.append(event)

    model = get_model(
        "mistral/mistral-small-latest",
        conversation_api=False,
        config=GenerateConfig(max_tokens=256, temperature=0.0),
    )
    response = await model.generate(
        input=[ChatMessageUser(content="This is a test string. What are you?")],
        on_stream=collect,
    )
    assert len(response.completion) >= 1
    streamed = "".join(e.text for e in events if isinstance(e, StreamTextEvent))
    assert streamed == response.completion
