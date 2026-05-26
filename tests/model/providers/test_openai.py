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
from inspect_ai.model._providers.openai import OpenAIAPI


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


def test_azure_openai_ad_token_forwards_headers_without_managed_identity(
    monkeypatch, mocker
) -> None:
    _clear_openai_auth_env(monkeypatch)
    resolve_azure_token_provider = mocker.patch(
        "inspect_ai.model._providers.openai.resolve_azure_token_provider",
        side_effect=AssertionError("managed identity should not be resolved"),
    )
    azure_client = mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
    http_client = mocker.Mock(is_closed=False)

    api = OpenAIAPI(
        "azure/gpt-4o",
        base_url="https://example.openai.azure.com",
        azure_ad_token="entra-token",
        default_headers={"projectID": "project-123"},
        http_client=http_client,
    )

    resolve_azure_token_provider.assert_not_called()
    azure_client.assert_called_once()
    kwargs = azure_client.call_args.kwargs
    assert api.api_key is None
    assert api.token_provider is None
    assert kwargs["api_key"] is None
    assert kwargs["azure_ad_token_provider"] is None
    assert kwargs["azure_ad_token"] == "entra-token"
    assert kwargs["default_headers"] == {"projectID": "project-123"}
    assert kwargs["azure_endpoint"] == "https://example.openai.azure.com"
    assert kwargs["http_client"] is http_client


def test_azure_openai_ad_token_provider_does_not_duplicate_sdk_arg(
    monkeypatch, mocker
) -> None:
    _clear_openai_auth_env(monkeypatch)
    resolve_azure_token_provider = mocker.patch(
        "inspect_ai.model._providers.openai.resolve_azure_token_provider",
        side_effect=AssertionError("managed identity should not be resolved"),
    )
    azure_client = mocker.patch("inspect_ai.model._providers.openai.AsyncAzureOpenAI")
    http_client = mocker.Mock(is_closed=False)

    def token_provider() -> str:
        return "entra-token"

    api = OpenAIAPI(
        "azure/gpt-4o",
        base_url="https://example.openai.azure.com",
        azure_ad_token_provider=token_provider,
        http_client=http_client,
    )

    resolve_azure_token_provider.assert_not_called()
    azure_client.assert_called_once()
    kwargs = azure_client.call_args.kwargs
    assert api.api_key is None
    assert api.token_provider is token_provider
    assert "azure_ad_token_provider" not in api.model_args
    assert kwargs["api_key"] is None
    assert kwargs["azure_ad_token_provider"] is token_provider
    assert kwargs["azure_endpoint"] == "https://example.openai.azure.com"


def _clear_openai_auth_env(monkeypatch) -> None:
    for name in [
        "OPENAI_API_KEY",
        "AZUREAI_OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZUREAI_OPENAI_BASE_URL",
        "AZURE_OPENAI_BASE_URL",
        "AZURE_OPENAI_ENDPOINT",
    ]:
        monkeypatch.delenv(name, raising=False)


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
