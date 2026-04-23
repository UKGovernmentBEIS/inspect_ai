import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, GenerateConfig
from inspect_ai.model._chat_message import (
    ChatMessageSystem,
    ChatMessageTool,
)
from inspect_ai.model._providers.sagemaker import (
    collapse_consecutive_messages,
    model_output_from_response,
    process_chat_message,
    process_content,
)
from inspect_ai.tool import ToolInfo
from inspect_ai.tool._tool_choice import ToolFunction

# -- Fixtures ----------------------------------------------------------------


def _make_api(**model_args: Any):
    """Create a SagemakerAPI instance with mocked aioboto3."""
    mock_aioboto3 = MagicMock()
    mock_aioboto3.Session.return_value = MagicMock()
    mock_aioboto3.__version__ = "13.0.0"

    with patch.dict(sys.modules, {"aioboto3": mock_aioboto3}):
        from inspect_ai.model._providers.sagemaker import SagemakerAPI

        return SagemakerAPI(
            model_name="test-endpoint",
            config=GenerateConfig(),
            region_name="us-west-2",
            **model_args,
        )


OPENAI_RESPONSE = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "default",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello world",
                "tool_calls": [],
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    },
}


# -- Constructor / config tests ----------------------------------------------


class TestSagemakerInit:
    def test_defaults(self):
        api = _make_api()
        assert api.endpoint_name == "test-endpoint"
        assert api.model_args["region_name"] == "us-west-2"
        assert api.model_args["read_timeout"] == 600
        assert api.model_args["connect_timeout"] == 60
        assert api.stream is False

    def test_stream_bool(self):
        api = _make_api(stream=True)
        assert api.stream is True

    def test_stream_string_true(self):
        api = _make_api(stream="true")
        assert api.stream is True

    def test_stream_string_false(self):
        api = _make_api(stream="false")
        assert api.stream is False

    def test_stream_string_True(self):
        api = _make_api(stream="True")
        assert api.stream is True

    def test_timeout_coercion_from_string(self):
        api = _make_api(read_timeout="300", connect_timeout="30")
        assert api.model_args["read_timeout"] == 300
        assert api.model_args["connect_timeout"] == 30
        assert isinstance(api.model_args["read_timeout"], int)
        assert isinstance(api.model_args["connect_timeout"], int)

    def test_custom_endpoint_url(self):
        api = _make_api(endpoint_url="https://custom.example.com")
        assert api.model_args["endpoint_url"] == "https://custom.example.com"

    def test_connection_key(self):
        api = _make_api()
        assert api.connection_key() == "test-endpoint"

    def test_max_tokens(self):
        api = _make_api()
        assert api.max_tokens() is not None

    def test_collapse_messages_flags(self):
        api = _make_api()
        assert api.collapse_user_messages() is True
        assert api.collapse_assistant_messages() is True


# -- should_retry tests ------------------------------------------------------


class TestShouldRetry:
    def test_retry_on_503(self):
        api = _make_api()
        ex = ClientError(
            {"Error": {"Code": "ModelError"}, "OriginalStatusCode": 503},
            "InvokeEndpoint",
        )
        assert api.should_retry(ex) is True

    def test_retry_on_504(self):
        api = _make_api()
        ex = ClientError(
            {"Error": {"Code": "ModelError"}, "OriginalStatusCode": 504},
            "InvokeEndpoint",
        )
        assert api.should_retry(ex) is True

    def test_no_retry_on_400(self):
        api = _make_api()
        ex = ClientError(
            {"Error": {"Code": "ModelError"}, "OriginalStatusCode": 400},
            "InvokeEndpoint",
        )
        assert api.should_retry(ex) is False

    def test_no_retry_on_non_model_error(self):
        api = _make_api()
        ex = ClientError(
            {"Error": {"Code": "ValidationError"}, "OriginalStatusCode": 503},
            "InvokeEndpoint",
        )
        assert api.should_retry(ex) is False

    def test_no_retry_on_non_client_error(self):
        api = _make_api()
        assert api.should_retry(RuntimeError("boom")) is False


# -- Request body building tests ---------------------------------------------


class TestBuildRequestBody:
    def test_basic_request_body(self):
        api = _make_api()
        config = GenerateConfig(max_tokens=100, temperature=0.5, top_p=0.9)
        messages = [{"role": "user", "content": "hello"}]
        body = api._build_request_body(config, messages, None, "auto")

        assert body["messages"] == messages
        assert body["max_tokens"] == 100
        assert body["temperature"] == 0.5
        assert body["top_p"] == 0.9
        assert "tools" not in body

    def test_optional_params_included(self):
        api = _make_api()
        config = GenerateConfig(
            max_tokens=100,
            temperature=0.5,
            top_p=0.9,
            top_k=50,
            stop_seqs=["STOP"],
            frequency_penalty=0.1,
            presence_penalty=0.2,
            seed=42,
        )
        body = api._build_request_body(config, [], None, "auto")

        assert body["top_k"] == 50
        assert body["stop"] == ["STOP"]
        assert body["frequency_penalty"] == 0.1
        assert body["presence_penalty"] == 0.2
        assert body["seed"] == 42

    def test_optional_params_excluded_when_none(self):
        api = _make_api()
        config = GenerateConfig(max_tokens=100, temperature=0)
        body = api._build_request_body(config, [], None, "auto")

        assert "top_k" not in body
        assert "stop" not in body
        assert "seed" not in body

    def test_extra_body_merged(self):
        api = _make_api()
        config = GenerateConfig(
            max_tokens=100,
            extra_body={"custom_param": "value"},
        )
        body = api._build_request_body(config, [], None, "auto")
        assert body["custom_param"] == "value"


# -- Tool choice tests -------------------------------------------------------


class TestToolChoice:
    def test_tool_choice_auto(self) -> None:
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "auto")
        assert body["tool_choice"] == "auto"

    def test_tool_choice_none(self) -> None:
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "none")
        assert body["tool_choice"] == "none"

    def test_tool_choice_any(self) -> None:
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "any")
        assert body["tool_choice"] == "required"

    def test_tool_choice_specific_function(self) -> None:
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, ToolFunction(name="my_tool"))
        assert body["tool_choice"] == {
            "type": "function",
            "function": {"name": "my_tool"},
        }


# -- Tools config tests ------------------------------------------------------


class TestToolsConfig:
    def test_no_tools(self):
        api = _make_api()
        assert api._prepare_tools_config([]) is None

    def test_tools_formatted(self):
        api = _make_api()
        tool = MagicMock(spec=ToolInfo)
        tool.name = "search"
        tool.description = "Search the web"
        tool.parameters = MagicMock()
        tool.parameters.model_dump.return_value = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }

        result = api._prepare_tools_config([tool])
        assert result is not None
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["description"] == "Search the web"


# -- vLLM config tests -------------------------------------------------------


class TestPrepareVllmConfig:
    def test_no_change_for_user_message(self):
        api = _make_api()
        config = GenerateConfig(max_tokens=100)
        messages = [ChatMessageUser(content="hello")]
        result = api._prepare_vllm_config(messages, config)
        assert result is config  # same object, not modified

    def test_sets_continuation_for_assistant_message(self):
        api = _make_api()
        config = GenerateConfig(max_tokens=100)
        messages = [ChatMessageAssistant(content="partial")]
        result = api._prepare_vllm_config(messages, config)
        assert result is not config
        assert result.extra_body["add_generation_prompt"] is False
        assert result.extra_body["continue_final_message"] is True

    def test_empty_input(self):
        api = _make_api()
        config = GenerateConfig(max_tokens=100)
        result = api._prepare_vllm_config([], config)
        assert result is config


# -- Message processing tests ------------------------------------------------


class TestProcessChatMessage:
    @pytest.mark.anyio
    async def test_system_message(self):
        msg = ChatMessageSystem(content="You are helpful")
        result = await process_chat_message(msg)
        assert result == {"role": "system", "content": "You are helpful"}

    @pytest.mark.anyio
    async def test_user_message(self):
        msg = ChatMessageUser(content="Hello")
        result = await process_chat_message(msg)
        assert result == {"role": "user", "content": "Hello"}

    @pytest.mark.anyio
    async def test_assistant_message(self):
        msg = ChatMessageAssistant(content="Hi there")
        result = await process_chat_message(msg)
        assert result == {"role": "assistant", "content": "Hi there"}

    @pytest.mark.anyio
    async def test_tool_message(self):
        msg = ChatMessageTool(content="result", tool_call_id="call_123")
        result = await process_chat_message(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"
        assert result["content"] == "result"


# -- Process content tests ---------------------------------------------------


class TestProcessContent:
    @pytest.mark.anyio
    async def test_string_passthrough(self):
        result = await process_content("hello")
        assert result == "hello"

    @pytest.mark.anyio
    async def test_single_text_returns_string(self):
        from inspect_ai._util.content import ContentText

        result = await process_content([ContentText(text="hello")])
        assert result == "hello"


# -- Collapse messages tests -------------------------------------------------


class TestCollapseConsecutiveMessages:
    def test_empty(self):
        assert collapse_consecutive_messages([], True, True) == []

    def test_no_collapse_different_roles(self):
        msgs = [
            ChatMessageUser(content="a"),
            ChatMessageAssistant(content="b"),
        ]
        result = collapse_consecutive_messages(msgs, True, True)
        assert len(result) == 2

    def test_collapse_user_messages(self):
        msgs = [
            ChatMessageUser(content="a"),
            ChatMessageUser(content="b"),
        ]
        result = collapse_consecutive_messages(msgs, True, False)
        assert len(result) == 1

    def test_no_collapse_when_disabled(self):
        msgs = [
            ChatMessageUser(content="a"),
            ChatMessageUser(content="b"),
        ]
        result = collapse_consecutive_messages(msgs, False, False)
        assert len(result) == 2

    def test_collapse_assistant_messages(self):
        msgs = [
            ChatMessageAssistant(content="a"),
            ChatMessageAssistant(content="b"),
        ]
        result = collapse_consecutive_messages(msgs, False, True)
        assert len(result) == 1


# -- model_output_from_response tests ----------------------------------------


class TestModelOutputFromResponse:
    def test_valid_openai_response(self):
        output = model_output_from_response(OPENAI_RESPONSE, [])
        assert output.completion == "Hello world"

    def test_stop_reason(self):
        output = model_output_from_response(OPENAI_RESPONSE, [])
        assert output.stop_reason == "stop"

    def test_usage_populated(self):
        output = model_output_from_response(OPENAI_RESPONSE, [])
        assert output.usage is not None
        assert output.usage.input_tokens == 10
        assert output.usage.output_tokens == 5
        assert output.usage.total_tokens == 15


# -- End-to-end generate (mocked) -------------------------------------------


class TestGenerate:
    @pytest.mark.anyio
    async def test_generate_non_streaming(self):
        api = _make_api()

        # Mock the async context manager client
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(
            return_value=json.dumps(OPENAI_RESPONSE).encode("utf-8")
        )
        mock_client.invoke_endpoint = AsyncMock(return_value={"Body": mock_body})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)

        model_output, model_call = result
        assert model_output.completion == "Hello world"
        mock_client.invoke_endpoint.assert_called_once()

        # Verify the request body structure
        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert sent_body["max_tokens"] == 100
        assert sent_body["temperature"] == 0
        assert sent_body["stream"] is False


# -- Completion mode (CPT) tests ---------------------------------------------

COMPLETION_RESPONSE = {
    "id": "cmpl-abc123",
    "object": "text_completion",
    "created": 1700000000,
    "model": "default",
    "choices": [
        {
            "index": 0,
            "text": "The answer is 42",
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 8,
        "completion_tokens": 5,
        "total_tokens": 13,
    },
}

COMPLETION_RESPONSE_WITH_LOGPROBS = {
    "id": "cmpl-abc123",
    "object": "text_completion",
    "created": 1700000000,
    "model": "default",
    "choices": [
        {
            "index": 0,
            "text": "The answer",
            "finish_reason": "stop",
            "logprobs": {
                "tokens": ["The", " answer"],
                "token_logprobs": [-0.5, -1.2],
                "top_logprobs": [
                    {"The": -0.5, "A": -1.0, "An": -2.0},
                    {" answer": -1.2, " result": -1.5, " value": -2.5},
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 8,
        "completion_tokens": 2,
        "total_tokens": 10,
    },
}


class TestCompletionModeInit:
    def test_completion_mode_default_false(self):
        api = _make_api()
        assert api.completion_mode is False

    def test_completion_mode_bool(self):
        api = _make_api(completion_mode=True)
        assert api.completion_mode is True

    def test_completion_mode_string_true(self):
        api = _make_api(completion_mode="True")
        assert api.completion_mode is True

    def test_completion_mode_string_false(self):
        api = _make_api(completion_mode="false")
        assert api.completion_mode is False

    def test_prompt_logprobs(self):
        api = _make_api(prompt_logprobs=1)
        assert api.prompt_logprobs == 1

    def test_prompt_logprobs_string_coercion(self):
        api = _make_api(prompt_logprobs="3")
        assert api.prompt_logprobs == 3
        assert isinstance(api.prompt_logprobs, int)

    def test_prompt_logprobs_default_none(self):
        api = _make_api()
        assert api.prompt_logprobs is None


class TestGenerateCompletion:
    def _mock_client(
        self, response_dict: dict[str, Any]
    ) -> tuple[AsyncMock, AsyncMock]:
        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(
            return_value=json.dumps(response_dict).encode("utf-8")
        )
        mock_client.invoke_endpoint = AsyncMock(return_value={"Body": mock_body})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx, mock_client

    @pytest.mark.anyio
    async def test_completion_mode_routes_to_generate_completion(self):
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="What is the meaning of life?")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)
        model_output, model_call = result

        assert model_output.completion == "The answer is 42"

        # Verify it sent a prompt (completions format), not messages (chat format)
        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert "prompt" in sent_body
        assert "messages" not in sent_body
        assert sent_body["stream"] is False

    @pytest.mark.anyio
    async def test_completion_prompt_built_from_messages(self):
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [
            ChatMessageSystem(content="You are helpful"),
            ChatMessageUser(content="Hello"),
            ChatMessageAssistant(content="Hi"),
            ChatMessageUser(content="Bye"),
        ]
        config = GenerateConfig(max_tokens=50, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert sent_body["prompt"] == "You are helpful\nHello\nHi\nBye"

    @pytest.mark.anyio
    async def test_completion_with_logprobs(self):
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE_WITH_LOGPROBS)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(
            max_tokens=100, temperature=0, logprobs=True, top_logprobs=3
        )

        result = await api.generate(messages, [], "auto", config)
        model_output, _ = result

        # Verify logprobs were parsed
        assert model_output.choices[0].logprobs is not None
        content_lps = model_output.choices[0].logprobs.content
        assert len(content_lps) == 2
        assert content_lps[0].token == "The"
        assert content_lps[0].logprob == -0.5
        assert content_lps[1].token == " answer"
        assert content_lps[1].logprob == -1.2

        # Verify top_logprobs
        assert content_lps[0].top_logprobs is not None
        assert len(content_lps[0].top_logprobs) == 3

        # Verify request body included logprobs param
        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert sent_body["logprobs"] == 3

    @pytest.mark.anyio
    async def test_completion_without_logprobs(self):
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)
        model_output, _ = result

        assert model_output.choices[0].logprobs is None

        # Verify request body did NOT include logprobs param
        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert "logprobs" not in sent_body

    @pytest.mark.anyio
    async def test_completion_logprobs_requires_both_flags(self):
        """logprobs=True without top_logprobs should not send logprobs param."""
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0, logprobs=True)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert "logprobs" not in sent_body

    @pytest.mark.anyio
    async def test_completion_with_prompt_logprobs(self):
        api = _make_api(completion_mode=True, prompt_logprobs=1)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert sent_body["prompt_logprobs"] == 1

    @pytest.mark.anyio
    async def test_completion_with_optional_params(self):
        api = _make_api(completion_mode=True)
        mock_ctx, mock_client = self._mock_client(COMPLETION_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(
            max_tokens=100, temperature=0, top_k=50, stop_seqs=["END"]
        )

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert sent_body["top_k"] == 50
        assert sent_body["stop"] == ["END"]

    @pytest.mark.anyio
    async def test_non_completion_mode_uses_chat(self):
        """Verify that without completion_mode, generate uses chat format."""
        api = _make_api()  # completion_mode defaults to False
        mock_ctx, mock_client = self._mock_client(OPENAI_RESPONSE)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)
        model_output, _ = result

        call_args = mock_client.invoke_endpoint.call_args
        sent_body = json.loads(call_args.kwargs["Body"])
        assert "messages" in sent_body
        assert "prompt" not in sent_body


# -- Streaming metadata tracking tests ---------------------------------------


class TestStreamingMetadataTracking:
    @pytest.mark.anyio
    async def test_streaming_tracks_metadata_across_chunks(self):
        """Verify that id, model, usage, and finish_reason are tracked.

        Tracked incrementally across chunks, not just from the last chunk.
        """
        api = _make_api(stream=True)

        # Simulate vLLM streaming: stop chunk arrives before usage chunk
        chunks = [
            # Content chunk
            {
                "id": "chatcmpl-123",
                "created": 1700000000,
                "model": "my-model",
                "choices": [
                    {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
                ],
            },
            # Stop chunk (finish_reason set, but no usage yet)
            {
                "id": "chatcmpl-123",
                "created": 1700000000,
                "model": "my-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            # Usage chunk (arrives last, no choices)
            {
                "id": "chatcmpl-123",
                "created": 1700000000,
                "model": "my-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            },
        ]

        # Build mock streaming response
        async def mock_event_stream():
            for chunk in chunks:
                yield {
                    "PayloadPart": {
                        "Bytes": f"data: {json.dumps(chunk)}".encode("utf-8")
                    }
                }

        mock_client = AsyncMock()
        mock_response = {"Body": mock_event_stream()}
        mock_client.invoke_endpoint_with_response_stream = AsyncMock(
            return_value=mock_response
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hi")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)
        model_output, model_call = result

        assert model_output.completion == "Hello"
        assert model_output.stop_reason == "stop"
        assert model_output.usage is not None
        assert model_output.usage.input_tokens == 10
        assert model_output.usage.output_tokens == 1

    @pytest.mark.anyio
    async def test_streaming_finish_reason_from_middle_chunk(self):
        """finish_reason in a non-last chunk should still be captured."""
        api = _make_api(stream=True)

        chunks = [
            {
                "id": "chatcmpl-456",
                "created": 1700000001,
                "model": "my-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "World"},
                        "finish_reason": "length",
                    }
                ],
            },
            # Final chunk with usage only
            {
                "id": "chatcmpl-456",
                "created": 1700000001,
                "model": "my-model",
                "choices": [],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        ]

        async def mock_event_stream():
            for chunk in chunks:
                yield {
                    "PayloadPart": {
                        "Bytes": f"data: {json.dumps(chunk)}".encode("utf-8")
                    }
                }

        mock_client = AsyncMock()
        mock_client.invoke_endpoint_with_response_stream = AsyncMock(
            return_value={"Body": mock_event_stream()}
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hi")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        result = await api.generate(messages, [], "auto", config)
        model_output, _ = result

        assert model_output.completion == "World"
        assert model_output.stop_reason == "max_tokens"


# -- InferenceComponentName tests --------------------------------------------


class TestInferenceComponentName:
    def test_default_none(self):
        api = _make_api()
        assert api.inference_component_name is None

    def test_set_from_model_args(self):
        api = _make_api(inference_component_name="my-ic")
        assert api.inference_component_name == "my-ic"

    @pytest.mark.anyio
    async def test_non_streaming_passes_inference_component_name(self):
        api = _make_api(inference_component_name="my-ic")

        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(
            return_value=json.dumps(OPENAI_RESPONSE).encode("utf-8")
        )
        mock_client.invoke_endpoint = AsyncMock(return_value={"Body": mock_body})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        assert call_args.kwargs["InferenceComponentName"] == "my-ic"

    @pytest.mark.anyio
    async def test_non_streaming_omits_when_none(self):
        api = _make_api()

        mock_client = AsyncMock()
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(
            return_value=json.dumps(OPENAI_RESPONSE).encode("utf-8")
        )
        mock_client.invoke_endpoint = AsyncMock(return_value={"Body": mock_body})

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint.call_args
        assert "InferenceComponentName" not in call_args.kwargs

    @pytest.mark.anyio
    async def test_streaming_passes_inference_component_name(self):
        api = _make_api(stream=True, inference_component_name="my-ic")

        chunks = [
            {
                "id": "chatcmpl-123",
                "created": 1700000000,
                "model": "my-model",
                "choices": [
                    {"index": 0, "delta": {"content": "Hi"}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        ]

        async def mock_event_stream():
            for chunk in chunks:
                yield {
                    "PayloadPart": {
                        "Bytes": f"data: {json.dumps(chunk)}".encode("utf-8")
                    }
                }

        mock_client = AsyncMock()
        mock_client.invoke_endpoint_with_response_stream = AsyncMock(
            return_value={"Body": mock_event_stream()}
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint_with_response_stream.call_args
        assert call_args.kwargs["InferenceComponentName"] == "my-ic"

    @pytest.mark.anyio
    async def test_streaming_omits_when_none(self):
        api = _make_api(stream=True)

        chunks = [
            {
                "id": "chatcmpl-123",
                "created": 1700000000,
                "model": "my-model",
                "choices": [
                    {"index": 0, "delta": {"content": "Hi"}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
        ]

        async def mock_event_stream():
            for chunk in chunks:
                yield {
                    "PayloadPart": {
                        "Bytes": f"data: {json.dumps(chunk)}".encode("utf-8")
                    }
                }

        mock_client = AsyncMock()
        mock_client.invoke_endpoint_with_response_stream = AsyncMock(
            return_value={"Body": mock_event_stream()}
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        api._create_client = MagicMock(return_value=mock_ctx)

        messages = [ChatMessageUser(content="Hello")]
        config = GenerateConfig(max_tokens=100, temperature=0)

        await api.generate(messages, [], "auto", config)

        call_args = mock_client.invoke_endpoint_with_response_stream.call_args
        assert "InferenceComponentName" not in call_args.kwargs
