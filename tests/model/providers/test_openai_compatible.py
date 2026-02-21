import subprocess

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


def auth_error(status_code: int = 401, message: str = "Unauthorized") -> APIStatusError:
    return APIStatusError(
        message=message,
        response=httpx.Response(
            request=httpx.Request(method="POST", url="https://example.com"),
            status_code=status_code,
            json={"message": message},
        ),
        body={"message": message},
    )


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


def test_api_key_cmd_takes_precedence_over_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY_CMD", "refresh-cmd")
    calls: list[str] = []

    def mock_run(
        command: str,
        *,
        shell: bool,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert shell is True
        assert check is True
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 0, stdout="cmd-key\n")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.subprocess.run", mock_run
    )

    api = OpenAICompatibleAPI(
        model_name="deepseek/deepseek-reasoner",
        base_url="https://example.com",
    )
    assert api.api_key == "cmd-key"
    assert calls == ["refresh-cmd"]


@pytest.mark.asyncio
async def test_api_key_cmd_refreshes_on_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY_CMD", "refresh-cmd")
    outputs = iter(["initial-key\n", "refreshed-key\n"])
    command_calls = 0

    def mock_run(
        command: str,
        *,
        shell: bool,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal command_calls
        command_calls += 1
        assert command == "refresh-cmd"
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs))

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.subprocess.run", mock_run
    )

    api = OpenAICompatibleAPI(
        model_name="deepseek/deepseek-reasoner",
        base_url="https://example.com",
    )

    calls = 0

    async def mock_generate_once(*args: object, **kwargs: object) -> ModelOutput:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise auth_error()
        return ModelOutput.from_content("deepseek/deepseek-reasoner", content="ok")

    monkeypatch.setattr(api, "_generate_once", mock_generate_once)

    result = await api.generate(
        input=[ChatMessageUser(content="hello")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
    )
    assert isinstance(result, ModelOutput)
    assert result.completion == "ok"
    assert api.api_key == "refreshed-key"
    assert calls == 2
    assert command_calls == 2


@pytest.mark.asyncio
async def test_api_key_cmd_fails_after_two_command_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY_CMD", "refresh-cmd")
    command_calls = 0

    def mock_run(
        command: str,
        *,
        shell: bool,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal command_calls
        command_calls += 1
        if command_calls == 1:
            return subprocess.CompletedProcess(command, 0, stdout="initial-key\n")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.subprocess.run", mock_run
    )

    api = OpenAICompatibleAPI(
        model_name="deepseek/deepseek-reasoner",
        base_url="https://example.com",
    )

    async def mock_generate_once(*args: object, **kwargs: object) -> ModelOutput:
        raise auth_error()

    monkeypatch.setattr(api, "_generate_once", mock_generate_once)

    with pytest.raises(APIStatusError):
        await api.generate(
            input=[ChatMessageUser(content="hello")],
            tools=[],
            tool_choice="none",
            config=GenerateConfig(),
        )

    assert api.api_key == "initial-key"
    assert command_calls == 3
