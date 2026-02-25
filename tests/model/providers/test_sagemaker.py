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
    def test_tool_choice_auto(self):
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "auto")
        assert body["tool_choice"] == "auto"

    def test_tool_choice_none(self):
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "none")
        assert body["tool_choice"] == "none"

    def test_tool_choice_any(self):
        api = _make_api()
        body: dict[str, Any] = {}
        api._add_tool_choice(body, "any")
        assert body["tool_choice"] == "required"

    def test_tool_choice_specific_function(self):
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
