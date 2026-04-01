import httpx
import pytest
from openai import APIStatusError
from test_helpers.utils import (
    skip_if_no_openai,
    skip_if_no_together,
    skip_if_no_together_base_url,
)

from inspect_ai._util.environ import environ_var
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    StopReason,
    get_model,
)
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.tool import ToolInfo


@skip_if_no_together
@skip_if_no_together_base_url
async def test_openai_compatible() -> None:
    model = get_model(
        "openai-api/together/MiniMaxAI/MiniMax-M2.5",
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


@pytest.mark.parametrize("strict_tools", [True, False])
def test_strict_tools_model_arg(strict_tools: bool) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        strict_tools=strict_tools,
    )

    tools = api.tools_to_openai([ToolInfo(name="test_tool", description="Test tool")])
    assert tools[0]["function"]["strict"] is strict_tools


def test_strict_tools_default_true() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )

    tools = api.tools_to_openai([ToolInfo(name="test_tool", description="Test tool")])
    assert tools[0]["function"]["strict"] is True


@skip_if_no_openai
async def test_openai_responses_compatible() -> None:
    with environ_var("OPENAI_BASE_URL", "https://api.openai.com/v1"):
        model = get_model("openai-api/openai/gpt-5", responses_api=True)
        message = ChatMessageUser(content="This is a test string. What are you?")
        response = await model.generate(input=[message])
        assert len(response.completion) >= 1


@pytest.mark.parametrize(
    ("status_code", "message", "stop_reason"),
    [
        pytest.param(
            400,
            "Requested input length 125000 exceeds maximum input length 40000",
            "model_length",
            id="deepinfra_model_length",
        ),
        pytest.param(400, "Bad Request", None, id="bad_request"),
        pytest.param(403, "Forbidden", None, id="forbidden"),
        pytest.param(500, "Internal Server Error", None, id="internal_server_error"),
    ],
)
def test_handle_bad_request(
    status_code: int, message: str, stop_reason: StopReason | None
) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    error = APIStatusError(
        message=message,
        response=httpx.Response(
            request=httpx.Request(method="POST", url="https://example.com"),
            status_code=status_code,
            json={"message": message},
        ),
        body={"message": message},
    )
    response = api.handle_bad_request(error)
    if stop_reason:
        assert isinstance(response, ModelOutput)
        assert message in response.completion
        assert response.stop_reason == stop_reason
    else:
        assert isinstance(response, APIStatusError)


@pytest.mark.parametrize(
    ("body", "expected_stop_reason"),
    [
        pytest.param(
            {
                "message": "blocked",
                "code": "invalid_prompt",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="invalid_prompt",
        ),
        pytest.param(
            {
                "message": "content issue",
                "code": "content_policy_violation",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="content_policy_violation",
        ),
        pytest.param(
            {
                "message": "filtered",
                "code": "content_filter",
                "type": "server_error",
            },
            "content_filter",
            id="content_filter_azure",
        ),
        pytest.param(
            {
                "message": "Your request was blocked by safety",
                "code": "some_other_code",
                "type": "invalid_request_error",
            },
            "content_filter",
            id="invalid_request_blocked_message",
        ),
        pytest.param(
            {
                "message": "This request has been flagged for potentially high-risk cyber activity.",
                "code": "cyber_policy",
                "type": "invalid_request",  # This is the error type for 5.4
            },
            "content_filter",
            id="cyber_policy",
        ),
        pytest.param(
            {
                "message": "Something else entirely",
                "code": "some_other_code",
                "type": "invalid_request_error",
            },
            None,
            id="invalid_request_not_blocked",
        ),
    ],
)
def test_handle_bad_request_content_filter(
    body: dict[str, str], expected_stop_reason: StopReason | None
) -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    error = APIStatusError(
        message=body["message"],
        response=httpx.Response(
            request=httpx.Request(method="POST", url="https://example.com"),
            status_code=400,
            json=body,
        ),
        body=body,
    )
    response = api.handle_bad_request(error)
    if expected_stop_reason:
        assert isinstance(response, ModelOutput)
        assert response.stop_reason == expected_stop_reason
    else:
        assert isinstance(response, APIStatusError)


async def test_initialize_recreates_closed_http_client() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    await api.http_client.aclose()
    assert api.http_client.is_closed
    api.initialize()
    assert not api.http_client.is_closed


def test_client_timeout_sets_http_timeout() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
    )
    timeout = api.http_client.timeout
    assert timeout.read == 1800.0
    assert timeout.write == 1800.0
    assert timeout.pool == 1800.0
    assert timeout.connect == 5.0


def test_client_timeout_default_uses_sdk_default() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
    )
    # SDK default is 600s
    assert api.http_client.timeout.read == 600.0


@pytest.mark.anyio
async def test_client_timeout_preserved_after_reinitialize() -> None:
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
    )
    await api.http_client.aclose()
    assert api.http_client.is_closed
    api.initialize()
    assert not api.http_client.is_closed
    assert api.http_client.timeout.read == 1800.0
    assert api.http_client.timeout.connect == 5.0


def test_user_supplied_http_client_not_overridden() -> None:
    custom_client = httpx.AsyncClient(timeout=httpx.Timeout(42.0))
    api = OpenAICompatibleAPI(
        model_name="openai-api/openai/gpt-5",
        api_key="test",
        base_url="https://example.com",
        client_timeout=1800.0,
        http_client=custom_client,
    )
    # user-supplied client should be used as-is
    assert api.http_client is custom_client
    assert api.http_client.timeout.read == 42.0
