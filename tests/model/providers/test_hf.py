import contextlib
import importlib
import sys
from concurrent.futures import Future
from threading import Thread
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import anyio
import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_torch,
    skip_if_no_transformers,
)

from inspect_ai._util._async import tg_collect
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._model_info import MODEL_INFO_LOOKUP_API_KEY


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


def _fake_module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    return module


@contextlib.contextmanager
def _hf_provider_with_fake_deps(
    monkeypatch: pytest.MonkeyPatch, **transformers_attrs: Any
) -> Iterator[ModuleType]:
    """Import the HF provider against stub `torch` and `transformers` modules."""
    fake_generation = _fake_module(
        "transformers.generation", StopStringCriteria=_FakeStopStringCriteria
    )
    monkeypatch.setitem(sys.modules, "transformers.generation", fake_generation)
    fake_transformers = _fake_module(
        "transformers",
        **{
            "AutoModelForCausalLM": object,
            "AutoTokenizer": object,
            "GenerationConfig": object,
            "PreTrainedTokenizerBase": object,
            "set_seed": lambda seed: None,
            "generation": fake_generation,
            **transformers_attrs,
        },
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    fake_torch = _fake_module(
        "torch",
        Tensor=object,
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
        cuda=SimpleNamespace(is_available=lambda: False),
        inference_mode=contextlib.nullcontext,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    module_name = "inspect_ai.model._providers.hf"
    previous_module = sys.modules.pop(module_name, None)
    try:
        yield importlib.import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)
        if previous_module is not None:
            sys.modules[module_name] = previous_module


@pytest.mark.parametrize(
    "model_args",
    [
        {},
        {"tokenizer": "custom-tokenizer"},
        {"model_path": "local-model"},
        {"model_path": "local-model", "tokenizer_path": "custom-tokenizer"},
    ],
)
@pytest.mark.parametrize(
    ("api_key", "expected_token"),
    [
        ("hf-test-token", "hf-test-token"),
        # the model info lookup placeholder is not a credential and must not be
        # sent to the Hub: passing it makes the request unauthenticated and
        # stops huggingface_hub falling back to HF_TOKEN or the cached login
        (MODEL_INFO_LOOKUP_API_KEY, None),
    ],
)
def test_hf_api_key_reaches_model_and_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
    model_args: dict[str, str],
    api_key: str,
    expected_token: str | None,
) -> None:
    model_calls: list[dict] = []
    tokenizer_calls: list[dict] = []

    class FakeAutoModelForCausalLM:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            model_calls.append({"args": args, "kwargs": kwargs})
            return MagicMock()

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            tokenizer_calls.append({"args": args, "kwargs": kwargs})
            return MagicMock()

    with _hf_provider_with_fake_deps(
        monkeypatch,
        AutoModelForCausalLM=FakeAutoModelForCausalLM,
        AutoTokenizer=FakeAutoTokenizer,
    ) as provider_module:
        provider_module.HuggingFaceAPI(
            model_name="private/model",
            api_key=api_key,
            **model_args,
        )

    assert model_calls[0]["kwargs"]["token"] == expected_token
    assert tokenizer_calls[0]["kwargs"]["token"] == expected_token


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


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_auto_model_class_selects_alternate_loader(monkeypatch) -> None:
    """auto_model_class must load the model via the named transformers class.

    Architectures such as the Mistral 3 series are not registered with
    AutoModelForCausalLM and must be loaded with e.g.
    AutoModelForImageTextToText.
    """
    # unused-ignore is listed because the ignore is environment-dependent:
    # it fires only when transformers is not installed.
    import transformers  # type: ignore[import-not-found,import-untyped,unused-ignore]

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    causal_calls: list[dict] = []
    alternate_calls: list[dict] = []

    def fake_causal(*args, **kwargs):
        causal_calls.append({"args": args, "kwargs": kwargs})
        return MagicMock()

    class FakeAltModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            alternate_calls.append({"args": args, "kwargs": kwargs})
            return MagicMock()

    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained", fake_causal
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained", lambda *a, **k: MagicMock()
    )
    monkeypatch.setattr(transformers, "FakeAltModel", FakeAltModel, raising=False)

    HuggingFaceAPI(model_name="EleutherAI/pythia-70m", auto_model_class="FakeAltModel")

    # the alternate class loads the model; the default is not used
    assert len(alternate_calls) == 1
    assert len(causal_calls) == 0


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_auto_model_class_rejects_unknown(monkeypatch) -> None:
    """An auto_model_class that is not a transformers attribute must be rejected."""
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained", lambda *a, **k: MagicMock()
    )

    with pytest.raises(ValueError, match="not a valid"):
        HuggingFaceAPI(
            model_name="EleutherAI/pythia-70m",
            auto_model_class="NoSuchAutoModelClass",
        )


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_chat_template_dict_methods() -> None:
    """Templates that call dict methods (e.g. Gemma's `message.get()`) must render."""
    model = get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.01,
        ),
        chat_template="{% for message in messages %}{{ message.get('reasoning', '') }}[{{ message['role'] }}] {{ message['content'] }}{% endfor %}",
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    chat = model.api.hf_chat([message], [])  # type: ignore[attr-defined]
    assert chat == "[user] Lorem ipsum dolor"


async def test_hf_chat_template_does_not_double_bos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat template that writes BOS must not get a second BOS at tokenize time.

    Regression test for #6350: the provider renders the chat template with
    tokenize=False and then tokenizes the rendered string, so the default
    add_special_tokens=True adds a second BOS for models whose template
    already writes one (e.g. Gemma, Llama 3).
    """
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        tokenizer = _FakeBosTokenizer("gemma")
        api = _fake_hf_api_with_tokenizer(
            provider,
            "fake-gemma",
            model,
            tokenizer,
            chat_template="{% for message in messages %}{{ message['content'] }}{% endfor %}",
        )
        await _generate_drained_together(
            provider, [(api, GenerateConfig(max_tokens=1), "hi")]
        )

    assert tokenizer.calls[0].get("add_special_tokens") is False
    assert tokenizer.tokenized[0][0] == 2
    assert tokenizer.tokenized[0][1] != 2


async def test_hf_explicit_add_special_tokens_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit tokenizer_call_args add_special_tokens=True must be honoured."""
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        tokenizer = _FakeBosTokenizer("gemma")
        api = _fake_hf_api_with_tokenizer(
            provider,
            "fake-gemma",
            model,
            tokenizer,
            chat_template="{% for message in messages %}{{ message['content'] }}{% endfor %}",
            tokenizer_call_args={"add_special_tokens": True},
        )
        await _generate_drained_together(
            provider, [(api, GenerateConfig(max_tokens=1), "hi")]
        )

    assert tokenizer.calls[0].get("add_special_tokens") is True
    assert tokenizer.tokenized[0][:2] == [2, 2]


async def test_hf_no_chat_template_keeps_default_special_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a chat template the prompt has no BOS, so tokenization is unchanged."""
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        tokenizer = _FakeBosTokenizer("gemma")
        api = _fake_hf_api_with_tokenizer(
            provider, "fake-gemma", model, tokenizer, use_chat_template=False
        )
        await _generate_drained_together(
            provider, [(api, GenerateConfig(max_tokens=1), "hi")]
        )

    assert "add_special_tokens" not in tokenizer.calls[0]
    assert tokenizer.tokenized[0][0] == 2


class _FakeStopStringCriteria:
    def __init__(self, tokenizer: Any, stop_strings: list[str]) -> None:
        self.stop_strings = tuple(stop_strings)


class _FakeTensor:
    def __init__(self, rows: list[list[int]]) -> None:
        self.rows = rows

    def to(self, device: str) -> "_FakeTensor":
        return self

    def size(self, dim: int) -> int:
        return len(self.rows[0]) if dim == 1 else len(self.rows)

    def __getitem__(self, index: tuple[slice, slice]) -> "_FakeTensor":
        rows, cols = index
        return _FakeTensor([row[cols] for row in self.rows[rows]])


class _FakeTokenizer:
    chat_template = None
    eos_token = "<eos>"

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, input: list[str], **kwargs: Any) -> dict[str, _FakeTensor]:
        # without a chat template each prompt is "user: <token id>\n"
        ids = [[int(text.split(":")[1])] for text in input]
        return {
            "input_ids": _FakeTensor(ids),
            "attention_mask": _FakeTensor([[1] for _ in ids]),
        }

    def batch_decode(self, sequences: _FakeTensor, **kwargs: Any) -> list[str]:
        return [f"{self.name}:{row}" for row in sequences.rows]


class _FakeGenerationConfig:
    def to_json_string(self, use_diff: bool = True) -> str:
        return '{"transformers_version": "0.0.0"}'


class _FakeModel:
    device = "cpu"
    generation_config = _FakeGenerationConfig()

    def __init__(
        self,
        token: int,
        error: Exception | None = None,
        hidden_states: Any = None,
    ) -> None:
        self.token = token
        self.error = error
        self.hidden_states = hidden_states
        self.calls: list[tuple[list[int], dict[str, Any]]] = []

    def generate(
        self, input_ids: _FakeTensor, attention_mask: _FakeTensor, **kwargs: Any
    ) -> SimpleNamespace:
        self.calls.append(([row[0] for row in input_ids.rows], kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            sequences=_FakeTensor([row + [self.token] for row in input_ids.rows]),
            logits=None,
            hidden_states=self.hidden_states,
        )


class _FakeBosTokenizer:
    """Mimics a Gemma/Llama 3 tokenizer: the chat template writes the BOS.

    `apply_chat_template` renders a string starting with a BOS token id, and
    `__call__` prepends a second BOS id unless `add_special_tokens=False`,
    matching `transformers` behaviour for a rendered template string.
    """

    chat_template = "fake-gemma-template"
    eos_token = "<eos>"
    bos_token_id = 2

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []
        self.tokenized: list[list[int]] = []

    def apply_chat_template(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        turns = "".join(
            f"<start_of_turn>{message['role']}\n{message['content']}<end_of_turn>\n"
            for message in messages
        )
        return f"<bos>{turns}<start_of_turn>model\n"

    def __call__(self, input: list[str], **kwargs: Any) -> dict[str, _FakeTensor]:
        self.calls.append(dict(kwargs))
        rows = []
        for text in input:
            # the rendered "<bos>" text tokenizes to a leading BOS id
            ids = [self.bos_token_id] + [100 + i for i in range(len(text.split()))]
            if kwargs.get("add_special_tokens", True):
                ids = [self.bos_token_id] + ids
            rows.append(ids)
            self.tokenized.append(ids)
        return {
            "input_ids": _FakeTensor(rows),
            "attention_mask": _FakeTensor([[1] * len(row) for row in rows]),
        }

    def batch_decode(self, sequences: _FakeTensor, **kwargs: Any) -> list[str]:
        return [f"{self.name}:{row}" for row in sequences.rows]


def _fake_hf_api_with_tokenizer(
    provider: ModuleType,
    name: str,
    model: _FakeModel,
    tokenizer: _FakeBosTokenizer,
    **api_kwargs: Any,
) -> Any:
    setattr(
        provider,
        "AutoModelForCausalLM",
        SimpleNamespace(from_pretrained=lambda *args, **kwargs: model),
    )
    setattr(
        provider,
        "AutoTokenizer",
        SimpleNamespace(from_pretrained=lambda *args, **kwargs: tokenizer),
    )
    return provider.HuggingFaceAPI(model_name=name, **api_kwargs)


def _fake_hf_api(provider: ModuleType, name: str, model: _FakeModel) -> Any:
    tokenizer = _FakeTokenizer(name)
    setattr(
        provider,
        "AutoModelForCausalLM",
        SimpleNamespace(from_pretrained=lambda *args, **kwargs: model),
    )
    setattr(
        provider,
        "AutoTokenizer",
        SimpleNamespace(from_pretrained=lambda *args, **kwargs: tokenizer),
    )
    return provider.HuggingFaceAPI(model_name=name, use_chat_template=False)


def _generation_settings(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: [criteria.stop_strings for criteria in value]
        if key == "stopping_criteria"
        else value
        for key, value in kwargs.items()
    }


async def _hf_generate(api: Any, config: GenerateConfig, prompt: str) -> Any:
    try:
        return await api.generate(
            input=[ChatMessageUser(content=prompt)],
            tools=[],
            tool_choice="none",
            config=config,
        )
    except Exception as ex:
        return ex


async def _generate_drained_together(
    provider: ModuleType, requests: list[tuple[Any, GenerateConfig, str]]
) -> list[Any]:
    """Queue every request, then drain and generate them as the worker does."""
    # stops batched_generate() from starting the worker thread
    setattr(provider, "batch_thread", Thread())
    results: list[Any] = [None] * len(requests)

    async def run(i: int, api: Any, config: GenerateConfig, prompt: str) -> None:
        results[i] = await _hf_generate(api, config, prompt)

    async with anyio.create_task_group() as tg:
        for i, (api, config, prompt) in enumerate(requests):
            tg.start_soon(run, i, api, config, prompt)
        while provider.batch_queue.qsize() < len(requests):
            await anyio.sleep(0.01)
        while not provider.batch_queue.empty():
            for batch in provider._drain_batches(provider.batch_queue, timeout=0):
                provider._generate_batch(batch)
    return results


async def test_hf_batches_requests_for_each_model_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model_a, model_b = _FakeModel(101), _FakeModel(202)
        api_a = _fake_hf_api(provider, "a", model_a)
        api_b = _fake_hf_api(provider, "b", model_b)
        config = GenerateConfig(temperature=0.5)

        # the real worker thread drains all three requests at once
        results = await tg_collect(
            [
                lambda: _hf_generate(api_a, config, "1"),
                lambda: _hf_generate(api_b, config, "2"),
                lambda: _hf_generate(api_a, config, "3"),
            ]
        )

    assert [result.completion for result in results] == [
        "a:[101]",
        "b:[202]",
        "a:[101]",
    ]
    assert [sorted(prompts) for prompts, _ in model_a.calls] == [[1, 3]]
    assert [prompts for prompts, _ in model_b.calls] == [[2]]


@pytest.mark.parametrize(
    ("config_a", "config_b", "setting", "value_a", "value_b"),
    [
        (
            GenerateConfig(temperature=0.5),
            GenerateConfig(temperature=0.9),
            "temperature",
            0.5,
            0.9,
        ),
        (
            GenerateConfig(max_tokens=5),
            GenerateConfig(max_tokens=10),
            "max_new_tokens",
            5,
            10,
        ),
        (
            GenerateConfig(stop_seqs=["x"]),
            GenerateConfig(stop_seqs=["y"]),
            "stopping_criteria",
            [("x",)],
            [("y",)],
        ),
    ],
)
async def test_hf_batches_requests_for_each_config_separately(
    monkeypatch: pytest.MonkeyPatch,
    config_a: GenerateConfig,
    config_b: GenerateConfig,
    setting: str,
    value_a: Any,
    value_b: Any,
) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        api = _fake_hf_api(provider, "a", model)
        await _generate_drained_together(
            provider, [(api, config_a, "1"), (api, config_b, "2"), (api, config_a, "3")]
        )

    assert len(model.calls) == 2
    assert {
        tuple(sorted(prompts)): _generation_settings(kwargs)[setting]
        for prompts, kwargs in model.calls
    } == {(1, 3): value_a, (2,): value_b}


async def test_hf_batches_same_model_and_config_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        api = _fake_hf_api(provider, "a", model)
        # equal configs, but each call builds its own partials and stop criteria
        results = await _generate_drained_together(
            provider,
            [
                (api, GenerateConfig(temperature=0.5, stop_seqs=["x"]), prompt)
                for prompt in ["1", "2", "3"]
            ],
        )

    assert [result.completion for result in results] == ["a:[101]"] * 3
    assert [sorted(prompts) for prompts, _ in model.calls] == [[1, 2, 3]]


async def test_hf_batches_respect_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        api = _fake_hf_api(provider, "a", model)
        config = GenerateConfig(max_connections=2)
        await _generate_drained_together(
            provider, [(api, config, prompt) for prompt in ["1", "2", "3"]]
        )

    assert [len(prompts) for prompts, _ in model.calls] == [2, 1]
    assert sorted(prompt for prompts, _ in model.calls for prompt in prompts) == [
        1,
        2,
        3,
    ]


async def test_hf_batches_generate_while_other_settings_keep_arriving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101)
        api = _fake_hf_api(provider, "a", model)
        # stops batched_generate() from starting the worker thread
        setattr(provider, "batch_thread", Thread())

        class ContinuousArrivals:
            """Never idle: each request after the first has its own settings."""

            def __init__(self, first: Any) -> None:
                self.first = first
                self.reads = 0

            def get(self, timeout: float) -> Any:
                self.reads += 1
                if self.reads == 1:
                    return self.first
                if self.reads > 1000:
                    raise AssertionError("drain did not return")
                return provider._QueueItem(
                    input=self.first.input,
                    future=Future(),
                    key=("other settings", self.reads),
                )

        results: list[Any] = []

        async def run() -> None:
            results.append(await _hf_generate(api, GenerateConfig(), "1"))

        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            while provider.batch_queue.qsize() < 1:
                await anyio.sleep(0.01)
            arrivals = ContinuousArrivals(provider.batch_queue.get())
            for batch in provider._drain_batches(arrivals, timeout=2):
                provider._generate_batch(batch)

    assert arrivals.reads == api.max_connections()
    assert [result.completion for result in results] == ["a:[101]"]


async def test_hf_batch_error_fails_only_its_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        api_a = _fake_hf_api(provider, "a", _FakeModel(101, error=RuntimeError("a")))
        api_b = _fake_hf_api(provider, "b", _FakeModel(202))
        config = GenerateConfig()
        results = await _generate_drained_together(
            provider, [(api_a, config, "1"), (api_b, config, "2")]
        )

    assert isinstance(results[0], RuntimeError)
    assert results[1].completion == "b:[202]"


async def test_hf_batch_error_after_a_result_fails_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Layer:
        def __getitem__(self, sample_index: int) -> SimpleNamespace:
            if sample_index > 0:
                raise RuntimeError("hidden states")
            return SimpleNamespace(tolist=lambda: [0.0])

    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        model = _FakeModel(101, hidden_states=((Layer(),),))
        api = _fake_hf_api(provider, "a", model)
        config = GenerateConfig()
        results = await _generate_drained_together(
            provider, [(api, config, "1"), (api, config, "2")]
        )

    # the first request in the batch keeps its result, the other gets the error
    errors = [result for result in results if isinstance(result, RuntimeError)]
    outputs = [result for result in results if not isinstance(result, Exception)]
    assert len(errors) == 1
    assert [output.completion for output in outputs] == ["a:[101]"]


async def test_hf_output_records_model_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each output records the chat template and generation config in effect."""
    import hashlib

    template = "{% for message in messages %}{{ message['content'] }}{% endfor %}"
    with _hf_provider_with_fake_deps(monkeypatch) as provider:
        api = _fake_hf_api_with_tokenizer(
            provider,
            "fake-gemma",
            _FakeModel(101),
            _FakeBosTokenizer("gemma"),
            chat_template=template,
        )
        [output] = await _generate_drained_together(
            provider, [(api, GenerateConfig(max_tokens=1), "hi")]
        )

    assert output.metadata["hf_model_config"] == {
        "chat_template": {
            "source": "model_arg",
            "name": None,
            "sha256": hashlib.sha256(template.encode()).hexdigest(),
        },
        "generation_config": {"source": "auto", "values": {}},
        "trust_remote_code": False,
    }


def _patch_hf_loaders(
    monkeypatch: pytest.MonkeyPatch,
    generation_config: Any,
    chat_template: str | dict[str, str] | None = "repo-template",
) -> Any:
    model = SimpleNamespace(generation_config=generation_config)
    tokenizer = SimpleNamespace(chat_template=chat_template, eos_token="</s>")
    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained",
        lambda *args, **kwargs: model,
    )
    monkeypatch.setattr(
        "transformers.AutoTokenizer.from_pretrained",
        lambda *args, **kwargs: tokenizer,
    )
    return model


def _repo_generation_config() -> Any:
    from transformers import GenerationConfig

    return GenerationConfig(
        eos_token_id=2,
        bos_token_id=1,
        temperature=0.1,
        repetition_penalty=1.5,
        sequence_bias={(42,): 10.0},
    )


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_generation_config_auto_keeps_repo_config(monkeypatch) -> None:
    """By default the repository's generation config is used and recorded."""
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    repo_config = _repo_generation_config()
    model = _patch_hf_loaders(monkeypatch, repo_config)

    api = HuggingFaceAPI(model_name="org/model")

    assert model.generation_config is repo_config
    recorded = api.repo_config.model_dump()
    assert recorded["chat_template"]["source"] == "tokenizer"
    assert recorded["generation_config"]["source"] == "auto"
    assert recorded["generation_config"]["values"]["repetition_penalty"] == 1.5
    assert recorded["generation_config"]["values"]["temperature"] == 0.1


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_generation_config_default_drops_repo_settings(monkeypatch) -> None:
    """generation_config=default discards repo sampling settings, keeps token ids."""
    from transformers import GenerationConfig

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    model = _patch_hf_loaders(monkeypatch, _repo_generation_config())

    api = HuggingFaceAPI(model_name="org/model", generation_config="default")

    config = model.generation_config
    defaults = GenerationConfig()
    assert config.eos_token_id == 2
    assert config.bos_token_id == 1
    assert config.repetition_penalty == defaults.repetition_penalty
    assert config.temperature == defaults.temperature
    assert config.sequence_bias is None
    assert api.repo_config.model_dump()["generation_config"] == {
        "source": "default",
        "values": {"bos_token_id": 1, "eos_token_id": 2},
    }


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_generation_config_loads_from_path(monkeypatch, tmp_path) -> None:
    """generation_config=<path> loads sampling settings from that path instead."""
    from transformers import GenerationConfig

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    GenerationConfig(eos_token_id=7, do_sample=True, top_p=0.9).save_pretrained(
        tmp_path
    )
    model = _patch_hf_loaders(monkeypatch, _repo_generation_config())

    api = HuggingFaceAPI(model_name="org/model", generation_config=str(tmp_path))

    # special token ids still come from the model repository
    assert model.generation_config.eos_token_id == 2
    assert model.generation_config.top_p == 0.9
    assert model.generation_config.repetition_penalty != 1.5
    assert model.generation_config.sequence_bias is None
    assert api.repo_config.model_dump()["generation_config"]["source"] == str(tmp_path)


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_generation_config_rejects_non_str(monkeypatch) -> None:
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    _patch_hf_loaders(monkeypatch, _repo_generation_config())

    with pytest.raises(ValueError, match="generation_config must be"):
        HuggingFaceAPI(model_name="org/model", generation_config={"top_p": 0.9})


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_model_config_records_disabled_chat_template(monkeypatch) -> None:
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    _patch_hf_loaders(monkeypatch, _repo_generation_config())

    api = HuggingFaceAPI(model_name="org/model", use_chat_template=False)

    assert api.repo_config.model_dump()["chat_template"] == {
        "source": None,
        "name": None,
        "sha256": None,
    }


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_model_config_hashes_named_chat_templates(monkeypatch) -> None:
    """Tokenizers may carry a dict of named templates rather than one string."""
    import hashlib
    import json

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    templates = {"tool_use": "b", "default": "a"}
    _patch_hf_loaders(monkeypatch, _repo_generation_config(), chat_template=templates)

    api = HuggingFaceAPI(model_name="org/model")

    expected = hashlib.sha256(
        json.dumps(templates, sort_keys=True).encode()
    ).hexdigest()
    assert api.repo_config.model_dump()["chat_template"] == {
        "source": "tokenizer",
        "name": None,
        "sha256": expected,
    }


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_model_config_round_trips_through_log(monkeypatch) -> None:
    """Recorded generation config values survive ModelOutput serialization."""
    from inspect_ai.model import ModelOutput
    from inspect_ai.model._providers.hf import HuggingFaceAPI

    _patch_hf_loaders(monkeypatch, _repo_generation_config())
    api = HuggingFaceAPI(model_name="org/model")
    output = ModelOutput.from_content(
        model="org/model",
        content="ok",
    )
    output.metadata = {"hf_model_config": api.repo_config.model_dump()}

    restored = ModelOutput.model_validate_json(output.model_dump_json())

    assert restored.metadata == output.metadata
    values = restored.metadata["hf_model_config"]["generation_config"]["values"]
    assert values["sequence_bias"] == {"(42,)": 10.0}


@skip_if_no_transformers
@skip_if_no_accelerate
@pytest.mark.parametrize("tool_use_template", ["tools-v1", "tools-v2"])
def test_hf_model_config_hashes_selected_named_template(
    monkeypatch, tool_use_template: str
) -> None:
    """A template name passed as chat_template is recorded by its contents."""
    import hashlib

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    templates = {"default": "a", "tool_use": tool_use_template}
    _patch_hf_loaders(monkeypatch, _repo_generation_config(), chat_template=templates)

    api = HuggingFaceAPI(model_name="org/model", chat_template="tool_use")

    assert api.repo_config.model_dump()["chat_template"] == {
        "source": "tokenizer",
        "name": "tool_use",
        "sha256": hashlib.sha256(tool_use_template.encode()).hexdigest(),
    }


@skip_if_no_transformers
@skip_if_no_torch
@pytest.mark.parametrize("source", ["default", "path"])
def test_hf_generation_config_override_survives_generate(source, tmp_path) -> None:
    """An adopted config must not be rebuilt from the model's legacy config.json.

    transformers 4.x rebuilds a generation config marked `_from_model_config`
    from the model config on `generate()` when its token ids are unchanged,
    which would restore the repository's legacy generation parameters.
    """
    import json

    torch = pytest.importorskip("torch")
    from transformers import GenerationConfig, GPT2Config, GPT2LMHeadModel

    from inspect_ai.model._providers.hf import resolve_generation_config

    # repetition_penalty here is a legacy generation parameter in config.json
    config = GPT2Config.from_dict(
        {
            "n_layer": 1,
            "n_head": 2,
            "n_embd": 16,
            "vocab_size": 100,
            "bos_token_id": 0,
            "eos_token_id": 1,
            "repetition_penalty": 1.5,
        }
    )
    model: Any = GPT2LMHeadModel(config)
    model.generation_config = GenerationConfig.from_model_config(config)
    trusted = {"_from_model_config": True, "bos_token_id": 0, "eos_token_id": 1}
    (tmp_path / "generation_config.json").write_text(json.dumps(trusted))

    model.generation_config = resolve_generation_config(
        "default" if source == "default" else str(tmp_path),
        model.generation_config,
        token=None,
    )
    model.generate(
        torch.tensor([[2, 3]]), max_new_tokens=2, do_sample=False, pad_token_id=1
    )

    assert model.generation_config.repetition_penalty != 1.5


@skip_if_no_transformers
@skip_if_no_accelerate
def test_hf_generation_config_object_passes_to_from_pretrained(monkeypatch) -> None:
    """A GenerationConfig object is still forwarded to from_pretrained()."""
    from transformers import GenerationConfig

    from inspect_ai.model._providers.hf import HuggingFaceAPI

    supplied = GenerationConfig(repetition_penalty=1.3)
    model_kwargs: dict[str, Any] = {}

    def fake_model_from_pretrained(*args: Any, **kwargs: Any) -> Any:
        model_kwargs.update(kwargs)
        return SimpleNamespace(generation_config=kwargs["generation_config"])

    _patch_hf_loaders(monkeypatch, _repo_generation_config())
    monkeypatch.setattr(
        "transformers.AutoModelForCausalLM.from_pretrained", fake_model_from_pretrained
    )

    api = HuggingFaceAPI(model_name="org/model", generation_config=supplied)

    assert model_kwargs["generation_config"] is supplied
    recorded = api.repo_config.model_dump()["generation_config"]
    assert recorded["source"] == "object"
    assert recorded["values"]["repetition_penalty"] == 1.3


def _custom_generation_config_class() -> Any:
    from transformers import GenerationConfig

    class CustomGenerationConfig(GenerationConfig):
        def __init__(self, **kwargs: Any) -> None:
            self.max_denoising_steps = kwargs.pop("max_denoising_steps", None)
            super().__init__(**kwargs)

    return CustomGenerationConfig


@skip_if_no_transformers
@skip_if_no_torch
def test_hf_generation_config_path_keeps_model_config_class(tmp_path) -> None:
    """A config loaded from a path uses the model's GenerationConfig subclass."""
    from inspect_ai.model._providers.hf import resolve_generation_config

    config_class = _custom_generation_config_class()
    config_class(max_denoising_steps=12, eos_token_id=7).save_pretrained(tmp_path)
    repo_config = config_class(max_denoising_steps=99, eos_token_id=2)

    config: Any = resolve_generation_config(str(tmp_path), repo_config, token=None)

    assert type(config) is config_class
    assert config.max_denoising_steps == 12
    assert config.eos_token_id == 2


@skip_if_no_transformers
@skip_if_no_torch
def test_hf_generation_config_default_rejects_config_subclass() -> None:
    """A subclass with model-specific settings has no meaningful default."""
    from inspect_ai.model._providers.hf import resolve_generation_config

    config_class = _custom_generation_config_class()
    repo_config = config_class(max_denoising_steps=99, eos_token_id=2)

    with pytest.raises(ValueError, match="CustomGenerationConfig"):
        resolve_generation_config("default", repo_config, token=None)
