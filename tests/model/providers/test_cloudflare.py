import pytest
from test_helpers.utils import skip_if_no_cloudflare, skip_if_no_openai_package

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, get_model


@pytest.mark.anyio
@skip_if_no_cloudflare
async def test_cloudflare_api() -> None:
    async with get_model(
        "cloudflare/@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    ) as model:
        message = "This is a test string. What are you?"
        response = await model.generate(input=message)
        assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_cloudflare
async def test_cloudflare_empty_assistant_message() -> None:
    """Gateway-hosted models reject empty assistant content — filled on replay."""
    async with get_model("cloudflare/moonshotai/kimi-k3") as model:
        response = await model.generate(
            input=[
                ChatMessageUser(content="Say hello."),
                ChatMessageAssistant(content=""),
                ChatMessageUser(content="Please continue."),
            ]
        )
        assert len(response.completion) >= 1


@skip_if_no_openai_package
async def test_cloudflare_fills_empty_assistant_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty assistant content (with or without tool calls) becomes NO_CONTENT."""
    from inspect_ai._util.constants import NO_CONTENT
    from inspect_ai.model._providers.cloudflare import CloudFlareAPI
    from inspect_ai.tool import ToolCall

    monkeypatch.setenv("CLOUDFLARE_API_KEY", "test-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-id")

    api = CloudFlareAPI(model_name="moonshotai/kimi-k3")
    messages = await api.messages_to_openai(
        [
            ChatMessageUser(content="Say hello."),
            ChatMessageAssistant(content=""),
            ChatMessageAssistant(
                content="",
                tool_calls=[ToolCall(id="call_1", function="lookup", arguments={})],
            ),
            ChatMessageAssistant(content="Hello!"),
        ]
    )
    assert messages[1]["content"] == NO_CONTENT
    assert messages[2]["content"] == NO_CONTENT
    assert messages[3]["content"] == "Hello!"


@skip_if_no_openai_package
def test_cloudflare_token_reported_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.model._providers.cloudflare import (
        CLOUDFLARE_API_KEY,
        CLOUDFLARE_API_TOKEN,
        CloudFlareAPI,
    )

    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(CLOUDFLARE_API_KEY, raising=False)
    monkeypatch.setenv(CLOUDFLARE_API_TOKEN, "source-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = CloudFlareAPI(model_name="@cf/meta/llama-3.1-8b-instruct-awq")

    # the key came from CLOUDFLARE_API_TOKEN, so that is the variable the hook
    # must be told about (not the derived CLOUDFLARE_API_KEY)
    assert seen[0] == (CLOUDFLARE_API_TOKEN, "source-key")
    assert all(name == CLOUDFLARE_API_TOKEN for name, _ in seen)
    assert api.api_key == "overridden-key"


@skip_if_no_openai_package
def test_cloudflare_api_key_reported_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.model._providers.cloudflare import (
        CLOUDFLARE_API_KEY,
        CLOUDFLARE_API_TOKEN,
        CloudFlareAPI,
    )

    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(CLOUDFLARE_API_TOKEN, raising=False)
    monkeypatch.setenv(CLOUDFLARE_API_KEY, "source-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = CloudFlareAPI(model_name="@cf/meta/llama-3.1-8b-instruct-awq")

    assert seen[0] == (CLOUDFLARE_API_KEY, "source-key")
    assert all(name == CLOUDFLARE_API_KEY for name, _ in seen)
    assert api.api_key == "overridden-key"
