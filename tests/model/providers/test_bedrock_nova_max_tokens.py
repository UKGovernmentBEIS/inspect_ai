"""Tests for Bedrock Nova maxTokens handling per reasoning effort.

Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/3767

AWS Nova Converse API only requires maxTokens to be unset when reasoning effort
is "high". For "low" and "medium", maxTokens is a normal supported parameter
and previously the code was silently dropping the user's max_tokens for ALL
reasoning effort levels.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai.model import ChatMessageUser, ModelInfo, set_model_info
from inspect_ai.model._model_info import clear_model_info_cache

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import BedrockAPI  # noqa: E402


def _make_nova_api(
    model_name: str = "amazon.nova-2-lite-v1:0",
) -> BedrockAPI:
    """Build a BedrockAPI bound to a Nova model without instantiating a session."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = model_name
    return api


def _make_claude_api() -> BedrockAPI:
    """Build a BedrockAPI bound to a Claude model."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "anthropic.claude-3-sonnet-20240229-v1:0"
    return api


def _nova_high_effort_reasoning(api: BedrockAPI, config: GenerateConfig) -> bool:
    """Mirror the gate used in BedrockAPI.generate() for testability."""
    reasoning_cfg = api.reasoning_config(config)
    return (
        api.is_nova()
        and reasoning_cfg.get("reasoningConfig", {}).get("maxReasoningEffort") == "high"
    )


def test_nova_low_effort_keeps_max_tokens():
    """reasoning_effort='low' on Nova should NOT trigger the maxTokens=None path."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="low", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_nova_medium_effort_keeps_max_tokens():
    """reasoning_effort='medium' on Nova should NOT trigger the maxTokens=None path."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="medium", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_nova_high_effort_drops_max_tokens():
    """reasoning_effort='high' on Nova IS the only case that should drop maxTokens."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="high", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is True


def test_nova_no_reasoning_keeps_max_tokens():
    """No reasoning_effort on Nova means no reasoningConfig at all → keep maxTokens."""
    api = _make_nova_api()
    config = GenerateConfig(max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


@pytest.mark.parametrize(
    "model_name",
    [
        "amazon.nova-2-lite-v1:0",
        "us.amazon.nova-2-lite-v1:0",
        "global.amazon.nova-2-lite-v1:0",
        "amazon.nova-lite-1-5-v1:0",
    ],
)
def test_reasoning_capable_nova_models_emit_reasoning_config(model_name: str):
    api = _make_nova_api(model_name)

    assert api.reasoning_config(GenerateConfig(reasoning_effort="medium")) == {
        "reasoningConfig": {
            "type": "enabled",
            "maxReasoningEffort": "medium",
        }
    }


@pytest.mark.parametrize(
    "model_name",
    [
        "amazon.nova-lite-v1:0",
        "us.amazon.nova-pro-v1:0",
        "amazon.nova-micro-v1:0",
        "amazon.nova-premier-v1:0",
        "amazon.nova-2-sonic-v1:0",
    ],
)
def test_unsupported_nova_models_omit_reasoning_config_with_warning(
    model_name: str, monkeypatch: pytest.MonkeyPatch
):
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.model._providers.bedrock.warn_once",
        lambda _logger, message: warnings.append(message),
    )
    api = _make_nova_api(model_name)

    assert api.reasoning_config(GenerateConfig(reasoning_effort="high")) == {}
    assert warnings == [
        f"bedrock model '{model_name}' does not support "
        "'reasoning_effort'; ignoring it."
    ]
    assert (
        _nova_high_effort_reasoning(
            api, GenerateConfig(reasoning_effort="high", max_tokens=2048)
        )
        is False
    )


def test_unsupported_nova_without_reasoning_effort_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
):
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.model._providers.bedrock.warn_once",
        lambda _logger, message: warnings.append(message),
    )
    api = _make_nova_api("us.amazon.nova-pro-v1:0")

    assert api.reasoning_config(GenerateConfig()) == {}
    assert warnings == []


def test_claude_high_effort_keeps_max_tokens():
    """Claude is not Nova, so the Nova-specific high-effort path never fires."""
    api = _make_claude_api()
    config = GenerateConfig(reasoning_effort="high", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_nova_top_k_uses_nova_inference_config_extension():
    api = _make_nova_api()
    config = GenerateConfig(top_k=50)
    fields = api._additional_model_request_fields(config, False)
    assert fields == {"inferenceConfig": {"topK": 50}}


def test_claude_top_k_keeps_existing_bedrock_shape():
    api = _make_claude_api()
    config = GenerateConfig(top_k=50)
    fields = api._additional_model_request_fields(config, False)
    assert fields == {"top_k": 50}


def test_adaptive_thinking_model_omits_top_k():
    api = _make_claude_api()
    config = GenerateConfig(top_k=50)
    fields = api._additional_model_request_fields(config, True)
    assert fields == {}


@pytest.mark.parametrize(
    "model_name,effort,expected_reasoning,expected_max_tokens",
    [
        ("us.amazon.nova-pro-v1:0", "high", False, 2048),
        ("us.amazon.nova-pro-v1:0", "low", False, 2048),
        ("amazon.nova-lite-v1:0", "high", False, 2048),
        ("amazon.nova-micro-v1:0", "high", False, 2048),
        ("amazon.nova-premier-v1:0", "high", False, 2048),
        ("global.amazon.nova-2-lite-v1:0", "high", True, None),
        ("us.amazon.nova-2-lite-v1:0", "low", True, 2048),
        ("amazon.nova-lite-1-5-v1:0", "medium", True, 2048),
        ("custom-nova-test", "medium", True, 2048),
        (
            "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-lite-v1:0",
            "medium",
            True,
            2048,
        ),
        (
            "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
            "high",
            False,
            2048,
        ),
    ],
)
@skip_if_trio
async def test_nova_generate_request(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    effort: Literal["low", "medium", "high"],
    expected_reasoning: bool,
    expected_max_tokens: int | None,
) -> None:
    captured: dict[str, Any] = {}

    class Client:
        async def converse(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "4"}]}
                },
                "stopReason": "end_turn",
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }

        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

    if model_name == "custom-nova-test":
        set_model_info(model_name, ModelInfo(family="amazon.nova-2-lite-v1:0"))
        request.addfinalizer(clear_model_info_cache)
    api = BedrockAPI(model_name=model_name, base_url=None, streaming=False)
    monkeypatch.setattr(api.session, "create_client", lambda **kwargs: Client())
    result = await api.generate(
        input=[ChatMessageUser(content="What is 2 + 2?")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(reasoning_effort=effort, max_tokens=2048),
    )
    assert isinstance(result, tuple)
    assert not isinstance(result[0], Exception)
    assert result[0].completion == "4"
    assert captured["modelId"] == model_name
    assert captured["inferenceConfig"].get("maxTokens") == expected_max_tokens
    fields = captured["additionalModelRequestFields"]
    if expected_reasoning:
        assert fields["reasoningConfig"] == {
            "type": "enabled",
            "maxReasoningEffort": effort,
        }
    else:
        assert "reasoningConfig" not in fields
