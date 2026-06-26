from collections.abc import Iterator
from typing import cast

import pytest

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelAPI,
    ModelInfo,
    ModelOutput,
    set_model_info,
)
from inspect_ai.model._model_info import clear_model_info_cache
from inspect_ai.model._openai_responses import ResponsesModelInfo
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.azureai import AzureAIAPI
from inspect_ai.model._providers.bedrock import BedrockAPI
from inspect_ai.model._providers.google import GoogleGenAIAPI
from inspect_ai.model._providers.grok import GrokAPI
from inspect_ai.model._providers.mistral import MistralAPI
from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI
from inspect_ai.model._providers.openrouter import OpenRouterAPI
from inspect_ai.model._providers.util.hf_handler import HFHandler


@pytest.fixture(autouse=True)
def reset_model_info() -> Iterator[None]:
    clear_model_info_cache()
    yield
    clear_model_info_cache()


def test_anthropic_alias_uses_family_for_capabilities() -> None:
    set_model_info("anthropic/custom-alias", ModelInfo(family="claude-opus-4-7"))
    api = AnthropicAPI.__new__(AnthropicAPI)
    api.model_name = "custom-alias"
    api.service = None

    assert api.model_family() == "claude-opus-4-7"
    assert api.is_claude_4_7()
    assert api.is_claude_4_opus()
    assert api.service_model_name() == "custom-alias"


def test_google_alias_uses_family_for_capabilities() -> None:
    set_model_info("google/custom-alias", ModelInfo(family="gemini-3-pro-preview"))
    api = GoogleGenAIAPI.__new__(GoogleGenAIAPI)
    api.model_name = "custom-alias"
    api.service = None

    assert api.is_gemini_3_plus()
    assert api.is_gemini_thinking_only()
    assert api.service_model_name() == "custom-alias"


def test_grok_alias_uses_family_for_capabilities() -> None:
    set_model_info("grok/custom-alias", ModelInfo(family="grok-4-1-fast-reasoning"))
    api = GrokAPI.__new__(GrokAPI)
    api.model_name = "custom-alias"

    assert api.is_grok_4()
    assert not api.is_grok_4_original()
    assert api.model_name == "custom-alias"


def test_grok_service_model_name_controls_wire_identity() -> None:
    class _AliasedGrokAPI(GrokAPI):
        def service_model_name(self) -> str:
            return "grok-4-1-fast-reasoning"

    api = _AliasedGrokAPI.__new__(_AliasedGrokAPI)
    ModelAPI.__init__(api, model_name="custom-alias", api_key="test-key")

    assert api.canonical_name() == "grok/grok-4-1-fast-reasoning"
    assert api.connection_key() == "test-key:grok-4-1-fast-reasoning"
    assert api.model_name == "custom-alias"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("family", "responses_api"),
    [("gpt-4o", False), ("gpt-5.5", True)],
)
async def test_openai_alias_uses_family_during_initialization(
    family: str, responses_api: bool
) -> None:
    set_model_info("openai/custom-alias", ModelInfo(family=family))
    api = OpenAIAPI(model_name="custom-alias", api_key="test-key")
    try:
        assert api.model_family() == family
        assert api.is_latest() is False
        assert api.responses_api is responses_api
        assert api.service_model_name() == "custom-alias"
        assert api.api_model_name() == "custom-alias"
    finally:
        await api.aclose()


@pytest.mark.anyio
async def test_openai_passes_family_separately_from_wire_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_responses(**kwargs: object) -> ModelOutput:
        captured.update(kwargs)
        return ModelOutput.from_content(model="custom-alias", content="ok")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai.generate_responses",
        fake_generate_responses,
    )
    set_model_info("openai/custom-alias", ModelInfo(family="gpt-5"))
    api = OpenAIAPI(model_name="custom-alias", api_key="test-key")
    try:
        await api.generate(
            input=[ChatMessageUser(content="hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(reasoning_summary="none"),
        )
        assert captured["model_name"] == "custom-alias"
        assert captured["model_family"] == "gpt-5"
        model_info = cast(ResponsesModelInfo, captured["model_info"])
        assert model_info.is_gpt_5()
        assert not model_info.is_gpt_5_plus()
    finally:
        await api.aclose()


@pytest.mark.anyio
async def test_openai_alias_uses_family_for_text_tokenization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_for: list[str] = []

    class _Encoding:
        def encode(self, text: str, disallowed_special: tuple[()]) -> list[int]:
            return [len(text)]

    def fake_encoding_for_model(model_name: str) -> _Encoding:
        encoded_for.append(model_name)
        return _Encoding()

    monkeypatch.setattr("tiktoken.encoding_for_model", fake_encoding_for_model)
    set_model_info("openai/custom-alias", ModelInfo(family="gpt-5"))
    api = OpenAIAPI.__new__(OpenAIAPI)
    api.model_name = "custom-alias"
    api.service = None

    assert await api.count_text_tokens("hello") == 1
    assert encoded_for == ["gpt-5"]


def test_model_family_falls_back_to_service_model_name() -> None:
    api = OpenAIAPI.__new__(OpenAIAPI)
    api.model_name = "azure/custom-deployment"
    api.service = "azure"

    assert api.model_family() == "custom-deployment"


def test_azureai_alias_uses_family_for_capabilities() -> None:
    set_model_info("custom-alias", ModelInfo(family="Llama-3.3-70B-Instruct"))
    api = AzureAIAPI.__new__(AzureAIAPI)
    api.model_name = "custom-alias"
    api.org_prefix = None

    assert api.is_llama()
    assert api.is_llama3()
    assert api.max_tokens() == 2048
    assert api.service_model_name() == "custom-alias"


def test_bedrock_alias_uses_family_for_capabilities() -> None:
    set_model_info("custom-alias", ModelInfo(family="claude-opus-4-7"))
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "custom-alias"

    assert api.is_claude()
    assert api.is_claude_4_7_or_later()
    assert not api.is_nova()
    assert api.model_name == "custom-alias"


def test_bedrock_alias_uses_family_for_default_max_tokens() -> None:
    set_model_info("custom-alias", ModelInfo(family="meta-llama/Llama-3-70B-Instruct"))
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "custom-alias"

    assert api.max_tokens() == 2048


def test_openai_compatible_alias_uses_family_for_request_shape() -> None:
    set_model_info("custom-alias", ModelInfo(family="gpt-5"))
    api = OpenAICompatibleAPI.__new__(OpenAICompatibleAPI)
    api.model_name = "service/custom-alias"
    api.service = "service"

    params = api.completion_params(GenerateConfig(max_tokens=100), tools=False)
    assert params["model"] == "custom-alias"
    assert params["max_completion_tokens"] == 100
    assert "max_tokens" not in params


def test_openai_compatible_provider_qualified_alias_uses_family() -> None:
    set_model_info("service/custom-alias", ModelInfo(family="gpt-5"))
    api = OpenAICompatibleAPI.__new__(OpenAICompatibleAPI)
    api.model_name = "service/custom-alias"
    api.service = "service"

    assert api.canonical_name() == "custom-alias"
    assert api.model_family() == "gpt-5"
    params = api.completion_params(GenerateConfig(max_tokens=100), tools=False)
    assert params["model"] == "custom-alias"
    assert params["max_completion_tokens"] == 100
    assert "max_tokens" not in params


@pytest.mark.anyio
async def test_openai_compatible_passes_family_separately_from_wire_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_generate_responses(**kwargs: object) -> ModelOutput:
        captured.update(kwargs)
        return ModelOutput.from_content(model="custom-alias", content="ok")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.generate_responses",
        fake_generate_responses,
    )
    set_model_info("custom-alias", ModelInfo(family="gpt-5"))
    api = OpenAICompatibleAPI(
        model_name="service/custom-alias",
        service="service",
        api_key="test-key",
        base_url="https://example.com",
        responses_api=True,
    )
    try:
        await api.generate(
            input=[ChatMessageUser(content="hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
        assert captured["model_name"] == "custom-alias"
        assert captured["model_family"] == "gpt-5"
        model_info = cast(ResponsesModelInfo, captured["model_info"])
        assert model_info.is_gpt_5()
        assert not model_info.is_gpt_5_plus()
    finally:
        await api.aclose()


def test_mistral_alias_uses_family_to_select_api() -> None:
    set_model_info("mistral/custom-alias", ModelInfo(family="voxtral-mini-latest"))
    api = MistralAPI(
        model_name="custom-alias",
        api_key="test-key",
        base_url="https://example.com",
    )

    assert api.conversation_api is False
    assert api.service_model_name() == "custom-alias"


def test_openrouter_alias_uses_family_for_cache_capability() -> None:
    set_model_info("anthropic/custom-alias", ModelInfo(family="claude-2.1"))
    api = OpenRouterAPI.__new__(OpenRouterAPI)
    api.model_name = "openrouter/anthropic/custom-alias"
    api.service = "OpenRouter"

    assert api._cache_prompt_enabled(GenerateConfig()) is False
    assert api.service_model_name() == "openrouter/anthropic/custom-alias"


@pytest.mark.anyio
async def test_openrouter_alias_uses_family_for_reasoning_replay() -> None:
    from inspect_ai._util.content import ContentReasoning
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._providers.openrouter import (
        OPENROUTER_REASONING_DETAILS_SIGNATURE,
    )

    signature = OPENROUTER_REASONING_DETAILS_SIGNATURE + (
        '[{"type": "reasoning.encrypted", "data": "encrypted", "id": "tool_1"}]'
    )
    message = ChatMessageAssistant(
        content=[ContentReasoning(reasoning="thinking", signature=signature)]
    )
    set_model_info("custom-alias", ModelInfo(family="google/gemini-3-pro-preview"))
    api = OpenRouterAPI.__new__(OpenRouterAPI)
    api.model_name = "custom-alias"
    api.service = "OpenRouter"

    converted = await api.messages_to_openai([message])
    assert "reasoning_details" not in converted[0]


def test_hf_handler_uses_family_for_parsing_and_alias_for_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_families: list[str] = []

    def fake_parse(response: str, model_family: str) -> tuple[str, list[str]]:
        parsed_families.append(model_family)
        return response, []

    monkeypatch.setattr(
        "inspect_ai.model._providers.util.hf_handler.model_specific_tool_parse",
        fake_parse,
    )
    handler = HFHandler("custom-alias", "mistral-large")
    message = handler.parse_assistant_response("response", [])

    assert parsed_families == ["mistral-large"]
    assert message.model == "custom-alias"
