import base64
import json

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._internal import parse_content_with_internal
from inspect_ai.model._openai import openai_completion_params


@pytest.mark.anyio
@skip_if_no_openai
async def test_openai_api() -> None:
    model = get_model(
        "openai/gpt-3.5-turbo",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@skip_if_no_openai
def test_openai_verbosity() -> None:
    log = eval(
        Task(dataset=[Sample(input="Please tell a story about toys.")]),
        model="openai/gpt-5.1",
        verbosity="low",
    )[0]
    assert log.status == "success"


def test_openai_completion_params_extra_body_not_mutated() -> None:
    config = GenerateConfig(
        extra_body={"metadata": {"source": "test"}, "reasoning": {"effort": "low"}}
    )

    for _ in range(2):
        params = openai_completion_params("gpt-4o-mini", config, tools=False)
        assert params["extra_body"] == {"reasoning": {"effort": "low"}}
        assert config.extra_body == {
            "metadata": {"source": "test"},
            "reasoning": {"effort": "low"},
        }


@skip_if_no_openai
async def test_openai_o_series_developer_messages() -> None:
    async def check_developer_messages(model_name: str):
        model = get_model(
            model_name,
            config=GenerateConfig(reasoning_effort="medium", parallel_tool_calls=True),
        )
        await model.generate(
            [
                ChatMessageSystem(content="I am a helpful assistant."),
                ChatMessageUser(content="What are you?"),
            ]
        )

    await check_developer_messages("openai/o3-mini")


@skip_if_no_openai
async def test_openai_o_series_reasoning_effort() -> None:
    async def check_reasoning_effort(model_name: str, effort: str = "medium"):
        model = get_model(
            model_name,
            config=GenerateConfig(reasoning_effort=effort, parallel_tool_calls=True),  # type: ignore
        )
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1

    await check_reasoning_effort("openai/o3-mini")
    await check_reasoning_effort("openai/gpt-5-mini", "minimal")


@skip_if_no_openai
async def test_openai_o_series_max_tokens() -> None:
    async def check_max_tokens(model_name: str):
        model = get_model(
            model_name,
            config=GenerateConfig(max_tokens=4096, reasoning_effort="low"),
        )
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1

    await check_max_tokens("openai/o3-mini")


@skip_if_no_openai
def test_openai_flex_requests():
    log = eval(
        Task(),
        model="openai/o4-mini",
        model_args=dict(service_tier="flex", client_timeout=1200),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_flex_requests_not_available():
    log = eval(
        Task(),
        model="openai/gpt-4o",
        model_args=dict(service_tier="flex", client_timeout=1200),
    )[0]
    assert log.status == "error"
    assert "Invalid service_tier argument" in str(log.error)


def encode_internal(obj):
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("utf-8")


# Valid cases
@pytest.mark.parametrize(
    "s,exp_content,exp_internal",
    [
        # Tag at start
        (
            f"<internal>{encode_internal({'foo': 1})}</internal>rest of content.",
            "rest of content.",
            {"foo": 1},
        ),
        # Tag in middle
        (
            f"before <internal>{encode_internal([1, 2, 3])}</internal> after",
            "before  after",
            [1, 2, 3],
        ),
        # Tag at end
        (
            f"content <internal>{encode_internal('bar')}</internal>",
            "content",
            "bar",
        ),
        # No tag
        ("no internal tag here", "no internal tag here", None),
        # Malformed tag (no close)
        ("<internal>notclosed", "<internal>notclosed", None),
    ],
)
def test_parse_content_with_internal_valid(s, exp_content, exp_internal):
    content, internal = parse_content_with_internal(s, "internal")
    assert content == exp_content
    assert internal == exp_internal


invalid_utf8_bytes = b"\xff\xfe\xfd"
invalid_utf8_b64 = base64.b64encode(invalid_utf8_bytes).decode("utf-8")


@pytest.mark.parametrize(
    "s,expected_exception",
    [
        # Valid base64 that decodes to invalid UTF-8 (e.g., bytes that are not valid UTF-8)
        ("<internal>" + invalid_utf8_b64 + "</internal>content", UnicodeDecodeError),
        # Invalid JSON after base64 decoding
        (
            f"<internal>{base64.b64encode(b'invalid json').decode('utf-8')}</internal>content",
            json.JSONDecodeError,
        ),
    ],
)
def test_parse_content_with_internal_invalid_encoding(s, expected_exception):
    with pytest.raises(expected_exception):
        parse_content_with_internal(s, "internal")


async def test_chat_completions_forwards_config_extra_headers():
    """config.extra_headers must reach the chat completions request (#same as responses/compatible)."""
    from unittest.mock import AsyncMock, MagicMock

    from openai._types import NOT_GIVEN
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice

    from inspect_ai.model._providers.openai_completions import generate_completions
    from inspect_ai.model._providers.util.hooks import HttpxHooks

    mock_completion = ChatCompletion.model_construct(
        id="chatcmpl-test",
        created=0,
        model="gpt-4o",
        object="chat.completion",
        choices=[
            Choice.model_construct(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage.model_construct(
                    role="assistant", content="hello"
                ),
            )
        ],
    )

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_completion)

    http_hooks = MagicMock(spec=HttpxHooks)
    http_hooks.start_request = MagicMock(return_value="req_1")
    http_hooks.end_request = MagicMock(return_value=None)

    openai_api = MagicMock()
    openai_api.api_model_name.return_value = "gpt-4o"
    openai_api.service_tier = None
    openai_api.is_o_series.return_value = False
    openai_api.is_gpt.return_value = True
    openai_api.is_gpt_5.return_value = False

    await generate_completions(
        client=client,
        http_hooks=http_hooks,
        model_name="gpt-4o",
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(extra_headers={"x-custom-header": "custom-value"}),
        prompt_cache_key=NOT_GIVEN,
        prompt_cache_retention=NOT_GIVEN,
        safety_identifier=NOT_GIVEN,
        openai_api=openai_api,
        batcher=None,
    )

    extra_headers = client.chat.completions.create.call_args.kwargs["extra_headers"]
    assert extra_headers["x-custom-header"] == "custom-value"
    assert extra_headers[HttpxHooks.REQUEST_ID_HEADER] == "req_1"


def test_openai_resolve_streaming_declines_azure_chat_completions() -> None:
    """Auto mode declines to stream Azure chat completions.

    Azure annotates every streamed choice chunk with `content_filter_results`,
    but the SDK stream accumulator keeps choice-level extras only from the
    first chunk, so an accumulated completion would report stale (or lose)
    content-filter stop details. A display-only on_stream request must not
    degrade results (explicit streaming=true keeps its lossy behavior, and
    the responses path is unaffected).
    """
    from typing import Any

    from inspect_ai.model._providers.openai import OpenAIAPI
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    async def collect(event: Any) -> None:
        pass

    def api(model_name: str = "azure/gpt-4o", **model_args: Any) -> OpenAIAPI:
        return OpenAIAPI(
            model_name=model_name,
            base_url="https://test.openai.azure.com",
            api_key="test-key",
            **model_args,
        )

    with model_stream_observer(ModelStreamObserver("openai/test", collect)):
        assert api()._resolve_streaming(use_responses=False) is False
        assert api()._resolve_streaming(use_responses=True) is True
        assert api("openai/gpt-4o")._resolve_streaming(use_responses=False) is True
        # explicit opt-in/opt-out still wins
        assert api(streaming=True)._resolve_streaming(use_responses=False) is True
        assert (
            api("openai/gpt-4o", streaming=False)._resolve_streaming(
                use_responses=False
            )
            is False
        )
    # without an on_stream callback, auto never streams
    assert api("openai/gpt-4o")._resolve_streaming(use_responses=False) is False


def test_openai_streaming_model_arg_normalized() -> None:
    """-M streaming=auto arrives as the YAML string "auto" and maps to auto."""
    from typing import Any

    from inspect_ai.model._providers.openai import OpenAIAPI

    def api(**model_args: Any) -> OpenAIAPI:
        return OpenAIAPI(model_name="openai/gpt-4o", api_key="test-key", **model_args)

    assert api().streaming is None
    assert api(streaming="auto").streaming is None
    assert api(streaming=True).streaming is True
    assert api(streaming=False).streaming is False
    # a typo'd value raises rather than silently forcing streaming on or off
    with pytest.raises(ValueError, match="streaming"):
        api(streaming="always")


async def test_openai_auto_stream_falls_back_when_server_rejects_streaming():
    """An on_stream-enabled stream the server rejects retries non-streamed.

    OpenAI rejects streaming per se with a 400 naming param="stream" (e.g.
    reasoning models on organizations that haven't completed verification);
    a display-only on_stream request must not fail a generate that succeeds
    without streaming (an explicit streaming=true opt-in still fails loudly).
    """
    from typing import Any
    from unittest.mock import AsyncMock, MagicMock

    import httpx
    from openai import BadRequestError
    from openai.types.chat import ChatCompletion, ChatCompletionMessage
    from openai.types.chat.chat_completion import Choice

    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.model._providers.openai import OpenAIAPI
    from inspect_ai.model._stream import ModelStreamObserver, model_stream_observer

    mock_completion = ChatCompletion.model_construct(
        id="chatcmpl-test",
        created=0,
        model="gpt-4o",
        object="chat.completion",
        choices=[
            Choice.model_construct(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage.model_construct(
                    role="assistant", content="hello"
                ),
            )
        ],
    )

    message = "Your organization must be verified to stream this model."
    stream_rejected = BadRequestError(
        message,
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://test/v1/chat/completions")
        ),
        body={
            "message": message,
            "type": "invalid_request_error",
            "param": "stream",
            "code": "unsupported_value",
        },
    )

    api = OpenAIAPI(model_name="gpt-4o", api_key="test-key")
    api.client = MagicMock()
    api.client.chat.completions.create = AsyncMock(
        side_effect=[stream_rejected, mock_completion]
    )

    async def collect(event: Any) -> None:
        pass

    with model_stream_observer(ModelStreamObserver("openai/test", collect)):
        result = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

    assert isinstance(result, tuple)
    output, _ = result
    assert isinstance(output, ModelOutput)
    assert output.completion == "hello"

    # the first request streamed, the retry did not
    calls = api.client.chat.completions.create.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["stream"] is True
    assert "stream" not in calls[1].kwargs


async def test_chat_completions_streaming_with_non_strict_tools():
    """Streaming a tool-using request must not require strict tools.

    The SDK's resource-level `.stream()` helper raises ValueError at
    request-build time for any function tool without `strict: true`
    (inspect never sets `strict` on this path), so streaming goes through
    a raw `create(stream=True)` call instead — a display-only on_stream
    callback must not fail tool-using generates.
    """
    from typing import Any
    from unittest.mock import AsyncMock, MagicMock

    from openai._types import NOT_GIVEN
    from openai.types.chat import ChatCompletionChunk

    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.model._providers.openai_completions import generate_completions
    from inspect_ai.model._providers.util.hooks import HttpxHooks
    from inspect_ai.tool import ToolInfo

    def chunk(payload: dict[str, Any]) -> ChatCompletionChunk:
        return ChatCompletionChunk.model_validate(
            dict(id="c1", object="chat.completion.chunk", created=0, model="gpt-4o")
            | payload
        )

    chunks = [
        chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            role="assistant",
                            tool_calls=[
                                dict(
                                    index=0,
                                    type="function",
                                    id="call_1",
                                    function=dict(name="get_weather", arguments=""),
                                )
                            ],
                        ),
                        finish_reason=None,
                    )
                ]
            )
        ),
        chunk(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(
                            tool_calls=[
                                dict(index=0, function=dict(arguments='{"city": "x"}'))
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            )
        ),
    ]

    class _FakeChunkStream:
        async def __aenter__(self) -> "_FakeChunkStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> Any:
            async def gen() -> Any:
                for c in chunks:
                    yield c

            return gen()

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_FakeChunkStream())

    http_hooks = MagicMock(spec=HttpxHooks)
    http_hooks.start_request = MagicMock(return_value="req_1")
    http_hooks.end_request = MagicMock(return_value=None)

    openai_api = MagicMock()
    openai_api.api_model_name.return_value = "gpt-4o"
    openai_api.service_tier = None
    openai_api.is_o_series.return_value = False
    openai_api.is_gpt.return_value = True
    openai_api.is_gpt_5.return_value = False

    tool = ToolInfo(name="get_weather", description="Get the weather for a city.")

    result = await generate_completions(
        client=client,
        http_hooks=http_hooks,
        model_name="gpt-4o",
        input=[ChatMessageUser(content="hi")],
        tools=[tool],
        tool_choice="auto",
        config=GenerateConfig(),
        prompt_cache_key=NOT_GIVEN,
        prompt_cache_retention=NOT_GIVEN,
        safety_identifier=NOT_GIVEN,
        openai_api=openai_api,
        batcher=None,
        streaming=True,
    )

    assert isinstance(result, tuple)
    output, _ = result
    assert isinstance(output, ModelOutput)
    assert output.choices[0].stop_reason == "tool_calls"
    tool_calls = output.choices[0].message.tool_calls
    assert tool_calls is not None
    assert tool_calls[0].function == "get_weather"
    assert tool_calls[0].arguments == {"city": "x"}

    # the wire request streamed with non-strict tools
    request = client.chat.completions.create.call_args.kwargs
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert "strict" not in request["tools"][0]["function"]


async def test_chat_completions_streaming_converts_mid_stream_safeguard_block() -> None:
    """A safeguard block raised mid-stream (as a plain APIError) becomes content_filter output."""
    from typing import Any
    from unittest.mock import AsyncMock, MagicMock

    import httpx2
    from openai import APIError
    from openai._types import NOT_GIVEN

    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.model._providers.openai_completions import generate_completions
    from inspect_ai.model._providers.util.hooks import HttpxHooks

    error = APIError(
        message="Your prompt was blocked by our content policy.",
        request=httpx2.Request("POST", "https://test/v1/chat/completions"),
        body=dict(
            message="Your prompt was blocked by our content policy.",
            type="invalid_request_error",
            code="content_policy_violation",
        ),
    )

    class _FakeStream:
        async def __aenter__(self) -> "_FakeStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> Any:
            async def gen() -> Any:
                raise error
                yield  # pragma: no cover

            return gen()

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_FakeStream())

    http_hooks = MagicMock(spec=HttpxHooks)
    http_hooks.start_request = MagicMock(return_value="req_1")
    http_hooks.end_request = MagicMock(return_value=None)

    openai_api = MagicMock()
    openai_api.api_model_name.return_value = "gpt-4o"
    openai_api.service_model_name.return_value = "gpt-4o"
    openai_api.service_tier = None
    openai_api.is_o_series.return_value = False
    openai_api.is_gpt.return_value = True
    openai_api.is_gpt_5.return_value = False

    result = await generate_completions(
        client=client,
        http_hooks=http_hooks,
        model_name="gpt-4o",
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        prompt_cache_key=NOT_GIVEN,
        prompt_cache_retention=NOT_GIVEN,
        safety_identifier=NOT_GIVEN,
        openai_api=openai_api,
        batcher=None,
        streaming=True,
    )

    assert isinstance(result, tuple)
    output, model_call = result
    assert isinstance(output, ModelOutput)
    assert output.choices[0].stop_reason == "content_filter"
    assert "blocked" in output.completion
    assert model_call.error is True
