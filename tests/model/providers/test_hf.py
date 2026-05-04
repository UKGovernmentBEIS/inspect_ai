from unittest.mock import MagicMock

import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_transformers,
)

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def model():
    return get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.01,
        ),
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
        tokenizer_call_args={"truncation": True, "max_length": 2},
    )


@pytest.fixture
def model_with_stop_seqs():
    DEFAULT_CHAT_TEMPLATE = (
        "{% for message in messages %}{{ message.content }}{% endfor %}"
    )
    model = get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=5,
            seed=42,
            temperature=0.001,
            stop_seqs=["w3"],
        ),
        # this allows us to run base models with the chat message scaffolding:
        chat_template=DEFAULT_CHAT_TEMPLATE,
        tokenizer_call_args={"truncation": True, "max_length": 10},
    )
    return model


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_api(model) -> None:
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert response.usage.input_tokens == 2
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_api_with_stop_seqs(model_with_stop_seqs) -> None:
    # This generates "https://www.w3.org" with pythia-70m greedy decoding
    message = ChatMessageUser(content="https://")
    response = await model_with_stop_seqs.generate(input=[message])
    assert response.completion == "www.w3"


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_api_fails(model) -> None:
    temp_before = model.config.temperature
    try:
        model.config.temperature = 0.0

        message = ChatMessageUser(content="Lorem ipsum dolor")
        with pytest.raises(Exception):
            await model.generate(input=[message])
    finally:
        model.config.temperature = temp_before


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_trust_remote_code_default_false(monkeypatch) -> None:
    """trust_remote_code must default to False on both model and tokenizer calls."""
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    calls: list[dict] = []

    def fake_from_pretrained(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return MagicMock()

    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained", fake_from_pretrained
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained", fake_from_pretrained
    )

    HuggingFaceAPI(model_name="EleutherAI/pythia-70m")

    assert len(calls) == 2
    for call in calls:
        assert call["kwargs"].get("trust_remote_code") is False


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_trust_remote_code_explicit_true(monkeypatch) -> None:
    """An explicit trust_remote_code=True must reach both from_pretrained calls."""
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    calls: list[dict] = []

    def fake_from_pretrained(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return MagicMock()

    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained", fake_from_pretrained
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained", fake_from_pretrained
    )

    HuggingFaceAPI(model_name="EleutherAI/pythia-70m", trust_remote_code=True)

    assert len(calls) == 2
    for call in calls:
        assert call["kwargs"].get("trust_remote_code") is True
    # trust_remote_code must be consumed, not also smuggled through **model_args
    # (it must appear exactly once per call, not duplicated as a positional/extra kwarg)
    for call in calls:
        kwargs = call["kwargs"]
        # only the explicit kwarg we passed; no duplicate via passthrough
        assert sum(1 for k in kwargs if k == "trust_remote_code") == 1


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_trust_remote_code_rejects_non_bool(monkeypatch) -> None:
    """Non-bool trust_remote_code (e.g. a string from a malformed config) must be rejected."""
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained", lambda *a, **k: MagicMock()
    )

    with pytest.raises(ValueError, match="trust_remote_code must be a bool"):
        HuggingFaceAPI(model_name="EleutherAI/pythia-70m", trust_remote_code="true")


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_disable_chat_template() -> None:
    model = get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.01,
        ),
        chat_template="{% for message in messages %}[{{ message.role }}] {{ message.content }}{% endfor %}",
        use_chat_template=False,
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    chat = model.api.hf_chat([message], [])  # type: ignore[attr-defined]
    assert chat == "user: Lorem ipsum dolor\n"
