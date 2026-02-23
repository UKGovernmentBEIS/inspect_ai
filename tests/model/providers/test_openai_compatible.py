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


@pytest.mark.asyncio
@skip_if_no_together
@skip_if_no_together_base_url
async def test_openai_compatible() -> None:
    model = get_model(
        "openai-api/together/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
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


@pytest.mark.asyncio
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
