"""Tests for prompt_logprobs config and response parsing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    TopLogprob,
)
from inspect_ai.model._openai import (
    _parse_prompt_logprobs,
    openai_completion_params,
)

# -- GenerateConfig tests --


def test_prompt_logprobs_config_field() -> None:
    """prompt_logprobs is None by default and can be set."""
    config = GenerateConfig()
    assert config.prompt_logprobs is None

    config = GenerateConfig(prompt_logprobs=1)
    assert config.prompt_logprobs == 1


def test_prompt_logprobs_config_accepts_range() -> None:
    """prompt_logprobs accepts values 1 through 20."""
    config = GenerateConfig(prompt_logprobs=1)
    assert config.prompt_logprobs == 1
    config = GenerateConfig(prompt_logprobs=5)
    assert config.prompt_logprobs == 5
    config = GenerateConfig(prompt_logprobs=20)
    assert config.prompt_logprobs == 20


def test_prompt_logprobs_config_rejects_out_of_range() -> None:
    """prompt_logprobs rejects values outside 1-20."""
    with pytest.raises(ValueError, match="prompt_logprobs must be between 1 and 20"):
        GenerateConfig(prompt_logprobs=0)
    with pytest.raises(ValueError, match="prompt_logprobs must be between 1 and 20"):
        GenerateConfig(prompt_logprobs=21)
    with pytest.raises(ValueError, match="prompt_logprobs must be between 1 and 20"):
        GenerateConfig(prompt_logprobs=-1)


def test_prompt_logprobs_config_merge() -> None:
    """prompt_logprobs merges correctly from override."""
    base = GenerateConfig(max_tokens=100)
    override = GenerateConfig(prompt_logprobs=1)
    merged = base.merge(override)
    assert merged.prompt_logprobs == 1
    assert merged.max_tokens == 100


def test_prompt_logprobs_config_merge_none_no_override() -> None:
    """prompt_logprobs=None in override does not overwrite base."""
    base = GenerateConfig(prompt_logprobs=1)
    override = GenerateConfig()
    merged = base.merge(override)
    assert merged.prompt_logprobs == 1


# -- openai_completion_params tests --


def test_completion_params_prompt_logprobs_in_extra_body() -> None:
    """prompt_logprobs is injected into extra_body."""
    config = GenerateConfig(prompt_logprobs=1)
    params = openai_completion_params("test-model", config, tools=False)
    assert "extra_body" in params
    assert params["extra_body"]["prompt_logprobs"] == 1


def test_completion_params_prompt_logprobs_none_no_extra_body() -> None:
    """No extra_body added when prompt_logprobs is None."""
    config = GenerateConfig()
    params = openai_completion_params("test-model", config, tools=False)
    assert "extra_body" not in params


def test_completion_params_prompt_logprobs_with_existing_extra_body() -> None:
    """prompt_logprobs merges with existing extra_body entries."""
    config = GenerateConfig(
        prompt_logprobs=1,
        extra_body={"custom_key": "custom_value"},
    )
    params = openai_completion_params("test-model", config, tools=False)
    assert params["extra_body"]["prompt_logprobs"] == 1
    assert params["extra_body"]["custom_key"] == "custom_value"


def test_completion_params_dedicated_field_wins_over_extra_body() -> None:
    """Dedicated prompt_logprobs field takes precedence over extra_body."""
    config = GenerateConfig(
        prompt_logprobs=1,
        extra_body={"prompt_logprobs": 10},
    )
    params = openai_completion_params("test-model", config, tools=False)
    # Dedicated config field is applied after extra_body, so it wins
    assert params["extra_body"]["prompt_logprobs"] == 1


# -- _parse_prompt_logprobs tests --
# Note: vLLM places prompt_logprobs at the response top level, not inside choices.
# The mock represents the ChatCompletion response object.


def test_parse_prompt_logprobs_from_model_extra() -> None:
    """Parses vLLM-style prompt logprobs from response.model_extra."""
    response = MagicMock()
    response.prompt_logprobs = None
    response.model_extra = {
        "prompt_logprobs": [
            None,  # first token has no logprob
            {"42": {"decoded_token": "Hello", "logprob": -0.5}},
            {"99": {"decoded_token": "world", "logprob": -1.2}},
        ]
    }

    result = _parse_prompt_logprobs(response)

    assert result is not None
    assert len(result.content) == 2
    assert result.content[0].token == "Hello"
    assert result.content[0].logprob == -0.5
    assert result.content[1].token == "world"
    assert result.content[1].logprob == -1.2


def test_parse_prompt_logprobs_from_attribute() -> None:
    """Parses prompt logprobs from response.prompt_logprobs attribute."""
    response = MagicMock()
    response.prompt_logprobs = [
        None,
        {"1": {"decoded_token": "The", "logprob": -0.3}},
    ]
    response.model_extra = None

    result = _parse_prompt_logprobs(response)

    assert result is not None
    assert len(result.content) == 1
    assert result.content[0].token == "The"
    assert result.content[0].logprob == -0.3


def test_parse_prompt_logprobs_none() -> None:
    """Returns None when no prompt logprobs are present."""
    response = MagicMock()
    response.prompt_logprobs = None
    response.model_extra = {}

    result = _parse_prompt_logprobs(response)
    assert result is None


def test_parse_prompt_logprobs_empty_list() -> None:
    """Returns None for an empty prompt logprobs list."""
    response = MagicMock()
    response.prompt_logprobs = []
    response.model_extra = None

    result = _parse_prompt_logprobs(response)
    assert result is None


def test_parse_prompt_logprobs_all_none_entries() -> None:
    """Returns None when all entries are None (e.g., single-token prompt)."""
    response = MagicMock()
    response.prompt_logprobs = [None]
    response.model_extra = None

    result = _parse_prompt_logprobs(response)
    assert result is None


def test_parse_prompt_logprobs_fallback_token_name() -> None:
    """Falls back to token_id string when decoded_token is missing."""
    response = MagicMock()
    response.prompt_logprobs = None
    response.model_extra = {
        "prompt_logprobs": [
            None,
            {"42": {"logprob": -0.8}},
        ]
    }

    result = _parse_prompt_logprobs(response)

    assert result is not None
    assert len(result.content) == 1
    assert result.content[0].token == "42"
    assert result.content[0].logprob == -0.8


def test_parse_prompt_logprobs_multiple_entries_populates_top_logprobs() -> None:
    """When multiple entries per position, first is prompt token, rest are top_logprobs."""
    response = MagicMock()
    response.prompt_logprobs = [
        None,
        {
            "46": {"decoded_token": "A", "logprob": -4.93, "rank": 28},
            "16": {"decoded_token": "#", "logprob": -1.62, "rank": 1},
            "25": {"decoded_token": "B", "logprob": -2.10, "rank": 3},
        },
    ]
    response.model_extra = None

    result = _parse_prompt_logprobs(response)

    assert result is not None
    assert len(result.content) == 1
    # First entry is the actual prompt token
    assert result.content[0].token == "A"
    assert result.content[0].logprob == -4.93
    # Remaining entries are alternatives in top_logprobs
    assert result.content[0].top_logprobs is not None
    assert len(result.content[0].top_logprobs) == 2
    assert result.content[0].top_logprobs[0].token == "#"
    assert result.content[0].top_logprobs[0].logprob == -1.62
    assert result.content[0].top_logprobs[1].token == "B"
    assert result.content[0].top_logprobs[1].logprob == -2.10


def test_parse_prompt_logprobs_single_entry_no_top_logprobs() -> None:
    """When only one entry per position (prompt_logprobs=1), no top_logprobs."""
    response = MagicMock()
    response.prompt_logprobs = [
        None,
        {"46": {"decoded_token": "A", "logprob": -4.93, "rank": 28}},
    ]
    response.model_extra = None

    result = _parse_prompt_logprobs(response)

    assert result is not None
    assert len(result.content) == 1
    assert result.content[0].token == "A"
    assert result.content[0].top_logprobs is None


def test_parse_prompt_logprobs_missing_logprob_raises() -> None:
    """Raises KeyError when a prompt token entry is missing the 'logprob' key."""
    response = MagicMock()
    response.prompt_logprobs = [
        None,
        {"42": {"decoded_token": "Hello"}},  # no "logprob" key
    ]
    response.model_extra = None

    with pytest.raises(KeyError, match="logprob"):
        _parse_prompt_logprobs(response)


def test_parse_prompt_logprobs_missing_alt_logprob_raises() -> None:
    """Raises KeyError when an alternative token entry is missing 'logprob'."""
    response = MagicMock()
    response.prompt_logprobs = [
        None,
        {
            "46": {"decoded_token": "A", "logprob": -4.93},
            "16": {"decoded_token": "#"},  # no "logprob" key
        },
    ]
    response.model_extra = None

    with pytest.raises(KeyError, match="logprob"):
        _parse_prompt_logprobs(response)


# -- ChatCompletionChoice backwards compatibility tests --


def _assistant_message() -> ChatMessageAssistant:
    return ChatMessageAssistant(content="hello", source="generate")


def test_choice_without_prompt_logprobs_defaults_to_none() -> None:
    """Constructing ChatCompletionChoice without prompt_logprobs still works."""
    choice = ChatCompletionChoice(
        message=_assistant_message(),
        stop_reason="stop",
    )
    assert choice.prompt_logprobs is None


def test_choice_with_prompt_logprobs() -> None:
    """Constructing ChatCompletionChoice with prompt_logprobs works."""
    lps = Logprobs(content=[Logprob(token="hi", logprob=-1.0)])
    choice = ChatCompletionChoice(
        message=_assistant_message(),
        stop_reason="stop",
        prompt_logprobs=lps,
    )
    assert choice.prompt_logprobs is not None
    assert len(choice.prompt_logprobs.content) == 1
    assert choice.prompt_logprobs.content[0].token == "hi"


def test_choice_with_prompt_logprobs_and_top_logprobs() -> None:
    """prompt_logprobs with top_logprobs populated (prompt_logprobs > 1)."""
    lps = Logprobs(
        content=[
            Logprob(
                token="A",
                logprob=-4.93,
                top_logprobs=[
                    TopLogprob(token="#", logprob=-1.62),
                    TopLogprob(token="B", logprob=-2.10),
                ],
            ),
        ]
    )
    choice = ChatCompletionChoice(
        message=_assistant_message(),
        stop_reason="stop",
        prompt_logprobs=lps,
    )
    assert choice.prompt_logprobs is not None
    assert choice.prompt_logprobs.content[0].top_logprobs is not None
    assert len(choice.prompt_logprobs.content[0].top_logprobs) == 2


def test_choice_deserialization_without_prompt_logprobs() -> None:
    """Old eval log data (no prompt_logprobs key) deserializes correctly."""
    old_log_data = {
        "message": {"role": "assistant", "content": "hello", "source": "generate"},
        "stop_reason": "stop",
        "logprobs": None,
    }
    choice = ChatCompletionChoice.model_validate(old_log_data)
    assert choice.prompt_logprobs is None
    assert choice.message.text == "hello"


def test_choice_deserialization_with_prompt_logprobs() -> None:
    """New eval log data (with prompt_logprobs) deserializes correctly."""
    new_log_data = {
        "message": {"role": "assistant", "content": "hello", "source": "generate"},
        "stop_reason": "stop",
        "logprobs": None,
        "prompt_logprobs": {
            "content": [
                {"token": "The", "logprob": -0.5},
                {"token": "end", "logprob": -1.2},
            ]
        },
    }
    choice = ChatCompletionChoice.model_validate(new_log_data)
    assert choice.prompt_logprobs is not None
    assert len(choice.prompt_logprobs.content) == 2
    assert choice.prompt_logprobs.content[0].token == "The"
    assert choice.prompt_logprobs.content[1].logprob == -1.2


def test_choice_roundtrip_serialization() -> None:
    """prompt_logprobs survives a serialize/deserialize round trip."""
    lps = Logprobs(content=[Logprob(token="x", logprob=-0.3)])
    original = ChatCompletionChoice(
        message=_assistant_message(),
        stop_reason="stop",
        logprobs=Logprobs(content=[]),
        prompt_logprobs=lps,
    )
    data = original.model_dump()
    restored = ChatCompletionChoice.model_validate(data)
    assert restored.prompt_logprobs is not None
    assert restored.prompt_logprobs.content[0].token == "x"
    assert restored.prompt_logprobs.content[0].logprob == -0.3


def test_choice_serialization_excludes_none_prompt_logprobs() -> None:
    """When prompt_logprobs is None, it serializes as None (not omitted)."""
    choice = ChatCompletionChoice(
        message=_assistant_message(),
        stop_reason="stop",
    )
    data = choice.model_dump()
    assert "prompt_logprobs" in data
    assert data["prompt_logprobs"] is None


# -- VLLMAPI.tokenize() tests --


@pytest.mark.anyio
async def test_vllm_tokenize_missing_tokens_key() -> None:
    """Raises ValueError when vLLM /tokenize returns 200 without 'tokens' key."""
    from inspect_ai.model._providers.vllm import VLLMAPI

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"error": "something went wrong"}

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)

    api = VLLMAPI.__new__(VLLMAPI)
    api.base_url = "http://localhost:8000/v1"
    api.api_key = None
    api.http_client = mock_http

    with (
        patch.object(api, "_ensure_server_started", new_callable=AsyncMock),
        patch.object(api, "service_model_name", return_value="test-model"),
    ):
        with pytest.raises(ValueError, match="missing 'tokens' key"):
            await api.tokenize("hello world")


@pytest.mark.anyio
async def test_vllm_tokenize_sends_add_special_tokens_false() -> None:
    """Ensures tokenize() passes add_special_tokens=False to vLLM /tokenize."""
    from inspect_ai.model._providers.vllm import VLLMAPI

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"tokens": [1, 2, 3]}

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)

    api = VLLMAPI.__new__(VLLMAPI)
    api.base_url = "http://localhost:8000/v1"
    api.api_key = None
    api.http_client = mock_http

    with (
        patch.object(api, "_ensure_server_started", new_callable=AsyncMock),
        patch.object(api, "service_model_name", return_value="test-model"),
    ):
        await api.tokenize("hello world")

    call_kwargs = mock_http.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["add_special_tokens"] is False


# -- VLLMCompletionsAPI extra_body precedence tests --


@pytest.mark.anyio
async def test_vllm_completions_dedicated_field_wins_over_extra_body() -> None:
    """Dedicated prompt_logprobs field takes precedence over extra_body.

    Same precedence as the chat completions path
    (test_completion_params_dedicated_field_wins_over_extra_body).
    """
    from inspect_ai.model._providers.vllm_completions import VLLMCompletionsAPI

    config = GenerateConfig(
        prompt_logprobs=1,
        max_tokens=1,
        extra_body={"prompt_logprobs": 10, "custom_key": "custom_value"},
    )

    # Create a minimal instance without calling __init__
    api = VLLMCompletionsAPI.__new__(VLLMCompletionsAPI)
    api.model_name = "test-model"

    # Mock the client and hooks
    mock_completion = MagicMock()
    mock_completion.model = "test-model"
    mock_completion.choices = []
    mock_completion.usage = None
    mock_completion.model_dump.return_value = {}

    mock_client = MagicMock()
    mock_client.completions = MagicMock()
    mock_client.completions.create = AsyncMock(return_value=mock_completion)
    api.client = mock_client

    mock_hooks = MagicMock()
    mock_hooks.start_request.return_value = "req-1"
    mock_hooks.end_request.return_value = 0.1
    api._http_hooks = mock_hooks

    with (
        patch.object(api, "service_model_name", return_value="test-model"),
        patch.object(api, "_ensure_server_started", new_callable=AsyncMock),
    ):
        from inspect_ai.model._chat_message import ChatMessageUser

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=config,
        )

    call_kwargs = mock_client.completions.create.call_args.kwargs
    # Dedicated config.prompt_logprobs=1 should override extra_body's 10
    assert call_kwargs["extra_body"]["prompt_logprobs"] == 1
    # Other extra_body keys are preserved
    assert call_kwargs["extra_body"]["custom_key"] == "custom_value"
