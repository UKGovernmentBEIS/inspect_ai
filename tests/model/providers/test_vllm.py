import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers.vllm import _server_context_length


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_api() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
            top_p=0.9,
            top_k=None,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        ),
        device=0,
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_server_context_length_matches_model_id() -> None:
    data = {
        "data": [
            {"id": "other/model", "max_model_len": 4096},
            {"id": "my/model", "max_model_len": 8192},
        ]
    }
    assert _server_context_length(data, "my/model") == 8192


def test_server_context_length_falls_back_to_sole_entry() -> None:
    data = {"data": [{"id": "served/model", "max_model_len": 8192}]}
    assert _server_context_length(data, "unmatched") == 8192


def test_server_context_length_ambiguous_no_match_returns_none() -> None:
    data = {
        "data": [
            {"id": "a/model", "max_model_len": 4096},
            {"id": "b/model", "max_model_len": 8192},
        ]
    }
    assert _server_context_length(data, "unmatched") is None


def test_server_context_length_missing_or_empty() -> None:
    assert (
        _server_context_length({"data": [{"id": "served/model"}]}, "served/model")
        is None
    )
    assert _server_context_length({"data": []}, "x") is None
    assert _server_context_length({}, "x") is None


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_disable_chat_template() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
        ),
        device=0,
        use_chat_template=False,
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
