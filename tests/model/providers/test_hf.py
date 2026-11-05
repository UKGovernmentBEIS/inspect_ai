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


class _FakeModel:
    device = "cpu"

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
