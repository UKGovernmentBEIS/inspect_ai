import ast
import json
import math
import multiprocessing
import pickle
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, NamedTuple, cast

import httpx2
import pytest
from click.testing import CliRunner
from pydantic import BaseModel, SecretStr
from test_helpers.output_cache import (
    concurrent_cache_entry,
    concurrent_cache_output,
    concurrent_cache_writer,
)
from test_helpers.utils import run_example

from inspect_ai import Task, eval, eval_async, eval_retry, task
from inspect_ai._cli.cache import cache_command
from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE
from inspect_ai._util import appdirs
from inspect_ai._util import logger as inspect_logger
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalSample, read_eval_log
from inspect_ai.model import (
    CachePolicy,
    ChatCompletionChoice,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Logprob,
    Logprobs,
    Model,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model import _cache as cache_module
from inspect_ai.model._cache import (
    _CACHE_KEY_DROPPED_FIELDS,
    _CACHE_KEY_NEUTRALIZED_FIELDS,
    CacheEntry,
    _cache_key_config,
    cache_clear,
    cache_fetch,
    cache_list_expired,
    cache_model_args_key,
    cache_path,
    cache_prune,
    cache_size,
    cache_store,
)
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.scorer import exact
from inspect_ai.solver import Generate, TaskState, generate, solver
from inspect_ai.tool import ToolCall, ToolInfo, ToolParam, ToolParams


async def test_cache_separates_model_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Constructor request defaults must not reuse a different model's answer."""
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("INSPECT_TRACE_FILE", str(tmp_path / "trace.log"))
    requests: list[str] = []

    async def send(
        self: httpx2.AsyncClient, request: httpx2.Request, **kwargs: Any
    ) -> httpx2.Response:
        system = json.loads(request.content)["system"]
        requests.append(system)
        return httpx2.Response(
            200,
            request=request,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": system}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(httpx2.AsyncClient, "send", send)
    means: list[float] = []
    cache_events: list[str | None] = []
    for system in ["3", "4", "4"]:
        model = get_model(
            "anthropic/claude-sonnet-4-6",
            api_key="test-key",
            base_url="https://cache-test.invalid",
            streaming=False,
            extra_body={"system": system},
            config=GenerateConfig(max_tokens=32, max_retries=0),
            memoize=False,
        )
        async with model:
            logs = await eval_async(
                Task(
                    dataset=[Sample(input="What is 2 + 2?", target="4")],
                    solver=generate(cache=True),
                    scorer=exact(),
                ),
                model=model,
                log_dir=str(tmp_path / "logs"),
                ctl_server=False,
            )
            log = logs[0]
        assert log.status == "success"
        assert log.results and log.samples
        means.append(log.results.scores[0].metrics["mean"].value)
        cache_events.extend(
            event.cache
            for event in log.samples[0].events
            if isinstance(event, ModelEvent)
        )

    assert means == [0.0, 1.0, 1.0]
    assert requests == ["3", "4"]
    assert cache_events == ["write", "write", "read"]


@pytest.mark.parametrize("credential", ["api_key", "aws_session_token"])
async def test_cache_shares_entries_across_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, credential: str
) -> None:
    """A rotated credential does not change the response."""
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    calls = 0

    async def generate_output(*args: Any, **kwargs: Any) -> ModelOutput:
        nonlocal calls
        calls += 1
        return ModelOutput.from_content(model="mockllm", content="3")

    for value in ["first", "rotated"]:
        credential_args: dict[str, Any] = {credential: value}
        model = get_model(
            "mockllm/model",
            memoize=False,
            extra_body={"system": "3"},
            **credential_args,
        )
        monkeypatch.setattr(model.api, "generate", generate_output)
        assert (await model.generate("Hello", cache=True)).completion == "3"
    assert calls == 1


_fail_after_generate = {"fail": False}


@solver
def _generate_then_fail_once():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state, cache=True)
        if _fail_after_generate["fail"]:
            _fail_after_generate["fail"] = False
            raise ValueError("fail once after generate")
        return state

    return solve


@task
def cached_generate_then_fail_once() -> Task:
    return Task(dataset=[Sample(input="Hello")], solver=_generate_then_fail_once())


def test_cache_hit_on_retry_from_logged_model_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The log drops credentials, so a retry rebuilds model args without them."""
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setitem(_fail_after_generate, "fail", True)
    log = eval(
        cached_generate_then_fail_once(),
        model="mockllm/model",
        model_args={"aws_session_token": "token", "extra_body": {"system": "3"}},
        log_dir=str(tmp_path / "logs"),
    )[0]
    assert log.status == "error"
    assert log.eval.model_args == {"extra_body": {"system": "3"}}

    retried = eval_retry(log, log_dir=str(tmp_path / "logs"))[0]
    assert retried.status == "success"
    assert retried.samples
    assert [
        event.cache
        for event in retried.samples[0].events
        if isinstance(event, ModelEvent)
    ] == ["read"]


def test_cache_model_args_key_is_stable() -> None:
    args = {"extra_body": {"system": "3", "options": [True, None, 0.5]}}
    same = {"extra_body": {"system": "3", "options": [True, None, 0.5]}}
    assert cache_model_args_key(args) == cache_model_args_key(same)
    assert cache_model_args_key(args) != cache_model_args_key(
        {"extra_body": {"system": "4", "options": [True, None, 0.5]}}
    )
    secret_key = cache_model_args_key({"key": "distinctive-secret"})
    assert secret_key and len(secret_key) == 64
    assert "distinctive-secret" not in secret_key
    assert cache_model_args_key({}) == ""


@pytest.mark.parametrize(
    "value", [object(), SecretStr("secret"), {1: "integer-key"}, float("nan")]
)
def test_cache_model_args_key_rejects_unsafe_values(value: Any) -> None:
    assert cache_model_args_key({"option": {"nested": value}}) is None


@pytest.mark.parametrize("instance_key", [None, "instance"])
def test_cache_model_args_key_keeps_dict_order(instance_key: str | None) -> None:
    """Providers resolve overlapping keys by order, so order is part of the key."""
    client = {"client": object()} if instance_key else {}
    headers_last_wins = cache_model_args_key(
        {**client, "default_headers": {"x-model-route": "3", "X-Model-Route": "4"}},
        instance_key=instance_key,
    )
    reversed_headers = cache_model_args_key(
        {**client, "default_headers": {"X-Model-Route": "4", "x-model-route": "3"}},
        instance_key=instance_key,
    )
    assert headers_last_wins != reversed_headers


async def test_cache_separates_google_safety_setting_alias_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The later of two aliases for one harm category is the one Google applies."""
    from inspect_ai.model._providers import google as google_provider

    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    # the provider mutates these shared defaults when it applies user settings
    monkeypatch.setattr(
        google_provider,
        "DEFAULT_SAFETY_SETTINGS",
        deepcopy(google_provider.DEFAULT_SAFETY_SETTINGS),
    )

    async def threshold_completion(safety_settings: dict[str, str]) -> str:
        model = get_model(
            "google/gemini-2.5-flash",
            api_key="test",
            safety_settings=safety_settings,
            memoize=False,
        )
        api = cast(google_provider.GoogleGenAIAPI, model.api)

        async def generate_output(*args: Any, **kwargs: Any) -> ModelOutput:
            threshold = next(
                str(setting["threshold"])
                for setting in api.safety_settings
                if "HARASSMENT" in str(setting["category"])
            )
            return ModelOutput.from_content(model="google", content=threshold)

        monkeypatch.setattr(model.api, "generate", generate_output)
        return (await model.generate("Hello", cache=True)).completion

    high = await threshold_completion(
        {"harassment": "low", "HARM_CATEGORY_HARASSMENT": "high"}
    )
    low = await threshold_completion(
        {"HARM_CATEGORY_HARASSMENT": "high", "harassment": "low"}
    )
    assert "HIGH" in high
    assert "LOW" in low


@pytest.mark.skipif(sys.get_int_max_str_digits() == 0, reason="no int conversion limit")
async def test_cache_defers_unserializable_model_args_to_caching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    model = get_model("mockllm/model", value=10**5000)
    assert (await model.generate("Hello")).completion
    with pytest.raises(ValueError):
        await model.generate("Hello", cache=True)


def test_cache_model_args_key_rejects_cycles() -> None:
    args: dict[str, Any] = {}
    args["cycle"] = args
    assert cache_model_args_key(args) is None
    assert cache_model_args_key(args, instance_key="instance") is not None


def test_cache_model_args_instance_key_preserves_json_arguments() -> None:
    client = object()
    args = {"client": client, "extra_body": {"system": "3", "options": [True]}}
    same = {"client": client, "extra_body": {"system": "3", "options": [True]}}
    key = cache_model_args_key(args, instance_key="first")
    assert key == cache_model_args_key(same, instance_key="first")
    assert key != cache_model_args_key(args, instance_key="second")
    args["extra_body"] = {"system": "4", "options": [True]}
    assert key != cache_model_args_key(args, instance_key="first")

    # An opaque node and a user's JSON value resembling its encoding differ.
    assert cache_model_args_key(
        {"client": client, "option": object()}, instance_key="first"
    ) != cache_model_args_key(
        {"client": client, "option": ["opaque"]}, instance_key="first"
    )


async def test_cache_key_uses_model_args_of_the_retried_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    extra_body = {"system": "3"}
    model = get_model("mockllm/model", extra_body=extra_body)
    calls = 0

    async def generate_output(*args: Any, **kwargs: Any) -> ModelOutput:
        nonlocal calls
        calls += 1
        if calls == 1:
            extra_body["system"] = "4"
            raise RuntimeError("transient")
        return ModelOutput.from_content(model="mockllm", content=extra_body["system"])

    monkeypatch.setattr(model.api, "generate", generate_output)
    monkeypatch.setattr(model.api, "should_retry", lambda ex: True)
    first = await model.generate("Hello", cache=True)
    extra_body["system"] = "3"
    second = await model.generate("Hello", cache=True)
    assert [first.completion, second.completion] == ["4", "3"]
    assert calls == 3


async def test_cache_scopes_opaque_model_args_to_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    base = get_model("mockllm/model")
    await base.generate("Hello", cache=True)

    class Opaque:
        def __repr__(self) -> str:
            raise AssertionError("Cache identity must not stringify opaque objects")

    client = Opaque()
    models = [get_model("mockllm/model", client=client) for _ in range(2)]
    calls = 0

    async def generate_output(*args: Any, **kwargs: Any) -> ModelOutput:
        nonlocal calls
        calls += 1
        return ModelOutput.from_content(model="mockllm", content=str(calls))

    inspect_logger._warned.clear()
    for index, model in enumerate(models, start=1):
        monkeypatch.setattr(model.api, "generate", generate_output)
        first = await model.generate("Hello", cache=True)
        second = await model.generate("Hello", cache=True)
        assert first.completion == str(index)
        assert second.completion == str(index)
    assert calls == 2
    assert "Model output caching is scoped to this model instance" in caplog.text
    assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 3
    inspect_logger._warned.clear()


def test_cache_examples():
    logs = run_example("cache.py", model="mockllm/model")
    assert all(log.status == "success" for log in logs)


def test_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # The miss-then-hit assertion below requires a cache no other test can
    # touch: under pytest-xdist a concurrent worker (e.g. test_cache_examples
    # exercising expiry policies) can evict entries from the shared cache dir
    # between the two evals.
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))

    # helper to check for cache hit
    def sample_cache_hit(sample: EvalSample) -> bool:
        return (
            sum(
                1
                for event in sample.events
                if (isinstance(event, ModelEvent) and event.cache == "read")
            )
            > 0
        )

    timestamp = str(datetime.now(timezone.utc))

    def check_eval_with_cache(cache_hit: bool):
        log = eval(
            Task(
                dataset=[Sample(input=f"What is the timestamp: {timestamp}")],
                solver=[generate(cache=True)],
            ),
            model="mockllm/model",
        )[0]
        assert log.samples
        assert sample_cache_hit(log.samples[0]) == cache_hit

    # first eval should miss the cache and the second should hit it
    check_eval_with_cache(False)
    check_eval_with_cache(True)


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_cache_policy_without_expiry_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, log_format: Literal["eval", "json"]
):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    log = eval(
        Task(dataset=[Sample(input="Hello")]),
        model="mockllm/model",
        cache=CachePolicy(expiry=None),
        log_dir=str(tmp_path / "logs"),
        log_format=log_format,
        display="none",
    )[0]

    log = read_eval_log(log.location)
    assert isinstance(log.eval.model_generate_config.cache, CachePolicy)
    assert log.eval.model_generate_config.cache.expiry is None
    assert log.samples
    model_event = next(e for e in log.samples[0].events if isinstance(e, ModelEvent))
    assert isinstance(model_event.config.cache, CachePolicy)
    assert model_event.config.cache.expiry is None


def test_cache_policy_missing_expiry_is_none_only_in_log_reads():
    assert CachePolicy.model_validate({}).expiry == "1W"
    assert CachePolicy().expiry == "1W"
    assert (
        CachePolicy.model_validate({}, context=get_deserializing_context()).expiry
        is None
    )


def _key_for(config: GenerateConfig) -> str:
    return CacheEntry(
        base_url=None,
        config=config,
        input=[ChatMessageUser(content="Hello")],
        model="mockllm/model",
        policy=CachePolicy(),
        tool_choice=None,
        tools=[],
    ).key


def test_cache_key_excludes_stream_idle_timeout():
    # stream_idle_timeout doesn't affect model output, so toggling it (or
    # setting it at all — keys written before the field existed must still
    # match) must not bust warm caches
    base_key = _key_for(GenerateConfig())
    assert _key_for(GenerateConfig(stream_idle_timeout=30)) == base_key
    assert _key_for(GenerateConfig(stream_idle_timeout=60)) == base_key

    # confirm the key is sensitive to output-affecting config
    assert _key_for(GenerateConfig(temperature=0.7)) != base_key


def test_cache_key_excludes_attempt_timeout_and_cache_prompt():
    # neither changes what the provider returns: attempt_timeout is a transport
    # deadline, and prompt caching is a cost optimization the provider serves
    # identical output through
    base_key = _key_for(GenerateConfig())
    assert _key_for(GenerateConfig(attempt_timeout=30)) == base_key
    assert _key_for(GenerateConfig(cache_prompt=True)) == base_key
    assert _key_for(GenerateConfig(cache_prompt="auto")) == base_key


def test_cache_key_neutralized_fields_preserve_existing_keys():
    # a config that sets none of the neutralized fields must serialize exactly
    # as it did while they were part of the key — otherwise classifying a field
    # silently invalidates every entry in every existing cache dir
    assert _cache_key_config(GenerateConfig()) == GenerateConfig().model_dump(
        exclude=_CACHE_KEY_DROPPED_FIELDS
    )


def _key_for_content(content: ContentText) -> str:
    return CacheEntry(
        base_url=None,
        config=GenerateConfig(),
        input=[ChatMessageUser(content=[content])],
        model="mockllm/model",
        policy=CachePolicy(),
        tool_choice=None,
        tools=[],
    ).key


def test_cache_key_excludes_content_cache_breakpoint():
    # cache_breakpoint is an Anthropic-caching operational hint, not something
    # that changes model output, so it must not affect the response-cache
    # identity — otherwise every persisted block-form entry (whose dump never
    # had this key before) misses the moment the field is introduced
    base_key = _key_for_content(ContentText(text="hello"))
    assert (
        _key_for_content(ContentText(text="hello", cache_breakpoint=None)) == base_key
    )
    assert (
        _key_for_content(ContentText(text="hello", cache_breakpoint=True)) == base_key
    )
    assert (
        _key_for_content(ContentText(text="hello", cache_breakpoint=False)) == base_key
    )

    # still sensitive to the actual text
    assert _key_for_content(ContentText(text="goodbye")) != base_key


def test_cache_key_excludes_fail_on_refusal():
    # fail_on_refusal never reaches the provider (and refusals are never
    # cached), so turning it on for an existing run must keep hitting the cache
    base_key = _key_for(GenerateConfig())
    assert _key_for(GenerateConfig(fail_on_refusal=True)) == base_key
    assert _key_for(GenerateConfig(fail_on_refusal=False)) == base_key


# Fields inert for the cache key (they never change what the provider returns)
# that nonetheless change sample *outcomes*, and so stay in eval-set task
# identity. The two classifications agree everywhere else.
_CACHE_NEUTRAL_OUTCOME_FIELDS = {"fail_on_refusal"}


def test_cache_key_neutral_fields_match_task_identity():
    """The cache key and task identity must agree on which config fields are inert.

    Both answer nearly the same question — can this field change what the
    provider returns — so a field classified for one and not the other is a
    bug in whichever list was missed. `attempt_timeout` and `cache_prompt` were
    part of the cache key for exactly that reason. The one sanctioned
    difference is `_CACHE_NEUTRAL_OUTCOME_FIELDS`: fields the provider never
    sees but that decide what happens to the sample.
    """
    assert (
        _CACHE_KEY_DROPPED_FIELDS | _CACHE_KEY_NEUTRALIZED_FIELDS
    ) - _CACHE_NEUTRAL_OUTCOME_FIELDS == GENERATE_CONFIG_FIELDS_TO_EXCLUDE, (
        "The cache key's inert GenerateConfig fields have drifted from "
        "GENERATE_CONFIG_FIELDS_TO_EXCLUDE (inspect_ai._eval.evalset).\n"
        "  → A field added to GenerateConfig and classified at the same time "
        "goes in _CACHE_KEY_DROPPED_FIELDS.\n"
        "  → A field that has already been part of the cache key goes in "
        "_CACHE_KEY_NEUTRALIZED_FIELDS, so existing cache entries survive."
    )


def test_cache_skips_content_filter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))

    def cache_entry() -> CacheEntry:
        return CacheEntry(
            base_url=None,
            config=GenerateConfig(),
            input=[ChatMessageUser(content="Hello")],
            model="mockllm/model",
            policy=CachePolicy(),
            tool_choice=None,
            tools=[],
        )

    # a content_filter refusal is not stored (a cached refusal would be
    # replayed on every refusal-retry with identical inputs)
    refusal = ModelOutput.from_content(
        model="mockllm/model", content="refused", stop_reason="content_filter"
    )
    assert cache_store(entry=cache_entry(), output=refusal) is False
    assert cache_fetch(cache_entry()) is None

    # other non-"stop" reasons still cache (the guard is content_filter-specific)
    truncated = ModelOutput.from_content(
        model="mockllm/model", content="partial", stop_reason="max_tokens"
    )
    assert cache_store(entry=cache_entry(), output=truncated) is True

    # a normal completion under the same key is stored and fetched
    completion = ModelOutput.from_content(model="mockllm/model", content="Hi")
    assert cache_store(entry=cache_entry(), output=completion) is True
    fetched = cache_fetch(cache_entry())
    assert fetched is not None
    assert fetched.completion == "Hi"


def test_cache_entry_from_before_input_context_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cached output without input_context_tokens reads it as None."""
    from inspect_ai.model._model_output import output_input_context_tokens

    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))

    timestamp = str(datetime.now(timezone.utc))

    def run_eval() -> EvalSample:
        log = eval(
            Task(
                dataset=[Sample(input=f"What is the timestamp: {timestamp}")],
                solver=[generate(cache=True)],
            ),
            model="mockllm/model",
        )[0]
        assert log.status == "success"
        assert log.samples
        return log.samples[0]

    run_eval()

    # rewrite the stored entry's output as an older ModelOutput would be
    entries = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(entries) == 1
    header, body = entries[0].read_bytes().splitlines()
    output = json.loads(body)
    output["usage"] = {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6}
    del output["input_context_tokens"]
    entries[0].write_bytes(header + b"\n" + json.dumps(output).encode() + b"\n")

    # a cache hit on that entry publishes and logs a usable output
    sample = run_eval()
    events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert [e.cache for e in events] == ["read"]
    assert events[0].output.input_context_tokens is None
    assert output_input_context_tokens(events[0].output) == 5


def test_cache_trace_omits_key_components(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    traced: list[str] = []
    monkeypatch.setattr(
        cache_module,
        "trace",
        lambda msg, *args: traced.append(msg % args if args else msg),
    )

    secret = "distinctive-message-content-1234"
    entry = CacheEntry(
        base_url=None,
        config=GenerateConfig(),
        input=[ChatMessageUser(content=secret)],
        model="mockllm/model",
        policy=CachePolicy(),
        tool_choice=None,
        tools=[],
    )
    output = ModelOutput.from_content(model="mockllm/model", content="Hi")
    assert cache_store(entry=entry, output=output) is True
    assert cache_fetch(entry) is not None

    # the trace log identifies entries by key, never by the (potentially
    # very large) conversation the key was computed from
    assert traced
    assert all(secret not in message for message in traced)
    assert any(entry.key in message for message in traced)


# A model name that walks out of the cache directory. With the cache root at
# <tmp>/a/b/c/generate it points at <tmp>/a/b/x.
_ESCAPING_MODEL = "openai/../../../x"

# Cache keys for planted entries.
_KEY = "0123456789abcdef0123456789abcdef"
_OTHER_KEY = "fedcba9876543210fedcba9876543210"


@pytest.fixture
def cache_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "a" / "b" / "c"))
    inspect_logger._warned.clear()
    yield cache_path()
    inspect_logger._warned.clear()


@pytest.fixture(params=["env", "default"])
def absent_cache_root(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Path]:
    # a cache root that does not exist yet, set by INSPECT_CACHE_DIR or found
    # in the default user cache directory
    base = tmp_path / "a" / "b" / "c"
    if request.param == "env":
        monkeypatch.setenv("INSPECT_CACHE_DIR", str(base))
    else:
        monkeypatch.delenv("INSPECT_CACHE_DIR", raising=False)
        monkeypatch.setattr(appdirs, "user_cache_path", lambda _name: base)
    inspect_logger._warned.clear()
    yield base / "generate"
    inspect_logger._warned.clear()


def _files_outside(root: Path, tmp_path: Path) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and root not in path.parents
    }


def _entry(model: str) -> CacheEntry:
    return CacheEntry(
        base_url=None,
        config=GenerateConfig(),
        input=[ChatMessageUser(content="Hello")],
        model=model,
        policy=CachePolicy(),
        tool_choice=None,
        tools=[],
    )


def _header(expiry: datetime | None, key: str, **fields: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "key": key,
        "expiry": expiry.isoformat() if expiry else None,
    } | fields


def _plant(
    path: Path,
    content: str,
    expiry: datetime | None,
    key: str | None = None,
    body: bytes | None = None,
) -> None:
    """Plant a current-format entry, with the key from its file name unless given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = _header(expiry, key or path.name.removesuffix(".jsonl"))
    if body is None:
        output = ModelOutput.from_content(model="m", content=content)
        body = output.model_dump_json().encode() + b"\n"
    path.write_bytes(json.dumps(header).encode() + b"\n" + body)


def _plant_legacy(path: Path, content: str, expiry: datetime | None) -> None:
    """Plant an entry as earlier versions of Inspect wrote it (a pickle)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    output = ModelOutput.from_content(model="m", content=content)
    path.write_bytes(pickle.dumps((expiry, output)))


_PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)
_FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)


def test_cache_store_and_fetch_stay_in_cache_dir(cache_root: Path, tmp_path: Path):
    entry = _entry(_ESCAPING_MODEL)
    outside = tmp_path / "a" / "b" / "x" / f"{entry.key}.jsonl"

    # store creates nothing outside the cache root
    output = ModelOutput.from_content(model="m", content="Hi")
    assert cache_store(entry=entry, output=output) is False
    assert not (tmp_path / "a" / "b" / "x").exists()

    # fetch does not read an entry planted where the name points
    _plant(outside, "planted", expiry=None)
    assert cache_fetch(entry) is None

    # nor delete an expired one
    _plant(outside, "planted", expiry=_PAST)
    before = _files_outside(cache_root, tmp_path)
    assert cache_fetch(entry) is None
    assert _files_outside(cache_root, tmp_path) == before

    # one warning for the model, however many times it is used
    assert len([m for m in inspect_logger._warned if _ESCAPING_MODEL in m]) == 1


@pytest.mark.parametrize(
    "model",
    [
        "/abs/path",
        "openai/..",
        "openai/./gpt-4",
        "openai\\..\\..\\..\\x",
        "openai/.../x",
        "C:\\x",
        "openai/gpt\0-4",
    ],
)
def test_cache_path_refuses_unsafe_model_names(cache_root: Path, model: str):
    with pytest.raises(ValueError):
        cache_path(model)
    entry = _entry(model)
    output = ModelOutput.from_content(model="m", content="Hi")
    assert cache_store(entry=entry, output=output) is False
    assert cache_fetch(entry) is None


@pytest.mark.skipif(sys.platform == "win32", reason="needs symlinks")
def test_cache_refuses_symlinks_out_of_cache_dir(cache_root: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (cache_root / "linked").symlink_to(outside, target_is_directory=True)

    # a model directory that is a symlink out of the cache
    entry = _entry("linked/model")
    output = ModelOutput.from_content(model="m", content="Hi")
    assert cache_store(entry=entry, output=output) is False
    assert list(outside.iterdir()) == []

    # entry files that are symlinks out of the cache: an expired current-format
    # entry and a legacy entry, each linked under its key-derived name
    entry = _entry("openai/gpt-4")
    target = outside / "entry"
    _plant(target, "planted", expiry=_PAST, key=entry.key)
    legacy_target = outside / "legacy"
    _plant_legacy(legacy_target, "planted", expiry=_PAST)
    model_dir = cache_path("openai/gpt-4")
    model_dir.mkdir(parents=True)
    link = model_dir / f"{entry.key}.jsonl"
    link.symlink_to(target)
    legacy_link = model_dir / entry.key
    legacy_link.symlink_to(legacy_target)
    assert cache_fetch(entry) is None
    assert cache_list_expired() == []
    cache_prune([link, legacy_link])
    assert target.exists() and legacy_target.exists()


def test_cache_clear_list_and_prune_stay_in_cache_dir(cache_root: Path, tmp_path: Path):
    outside = tmp_path / "a" / "b" / "x"
    expired = outside / f"{_KEY}.jsonl"
    legacy = outside / _OTHER_KEY
    _plant(expired, "planted", expiry=_PAST)
    _plant_legacy(legacy, "planted", expiry=_PAST)
    before = _files_outside(cache_root, tmp_path)

    assert cache_clear(_ESCAPING_MODEL) is False
    assert cache_list_expired([_ESCAPING_MODEL]) == []
    cache_prune([expired, legacy])
    assert _files_outside(cache_root, tmp_path) == before


def test_cache_layout_unchanged_for_normal_model_names(cache_root: Path):
    # entries are stored under the model directory as <key>.jsonl
    entry = _entry("openai/gpt-4")
    _plant(cache_root / "openai" / "gpt-4" / f"{entry.key}.jsonl", "existing", None)
    fetched = cache_fetch(entry)
    assert fetched is not None and fetched.completion == "existing"

    # a fresh store lands in the same place and round-trips
    entry = _entry("hf/org/Model-1.5:8b")
    output = ModelOutput.from_content(model="m", content="Hi")
    assert cache_store(entry=entry, output=output) is True
    assert (cache_root / "hf" / "org" / "Model-1.5:8b" / f"{entry.key}.jsonl").is_file()
    fetched = cache_fetch(entry)
    assert fetched is not None and fetched.completion == "Hi"

    # clear, list and prune still work by model name
    expired = cache_root / "openai" / "gpt-4" / f"{_KEY}.jsonl"
    legacy = cache_root / "openai" / "gpt-4" / _OTHER_KEY
    _plant(expired, "old", expiry=_PAST)
    _plant_legacy(legacy, "old", expiry=_FUTURE)
    pruneable = cache_list_expired(["openai/gpt-4"])
    assert sorted(pruneable) == sorted([expired, legacy])
    cache_prune(pruneable)
    assert not expired.exists() and not legacy.exists()
    assert cache_clear("openai/gpt-4") is True
    assert not (cache_root / "openai" / "gpt-4").exists()
    assert inspect_logger._warned == []


def test_cache_refusals_create_nothing(absent_cache_root: Path, tmp_path: Path):
    expired = tmp_path / f"{_KEY}.jsonl"
    legacy = tmp_path / _OTHER_KEY
    _plant(expired, "planted", expiry=_PAST)
    _plant_legacy(legacy, "planted", expiry=_PAST)

    entry = _entry(_ESCAPING_MODEL)
    output = ModelOutput.from_content(model="m", content="Hi")
    with pytest.raises(ValueError):
        cache_path(_ESCAPING_MODEL)
    assert cache_store(entry=entry, output=output) is False
    assert cache_fetch(entry) is None
    assert cache_clear(_ESCAPING_MODEL) is False
    assert cache_list_expired([_ESCAPING_MODEL]) == []
    cache_prune([expired, legacy])
    assert sorted(tmp_path.iterdir()) == sorted([expired, legacy])

    # the fixture does point the cache here: an accepted lookup creates it
    assert cache_path() == absent_cache_root
    assert absent_cache_root.is_dir()


def test_cache_prune_skips_unresolvable_paths(cache_root: Path):
    expired = cache_root / "openai" / "gpt-4" / f"{_KEY}.jsonl"
    _plant(expired, "old", expiry=_PAST)
    cache_prune([Path("invalid\0path"), expired])
    assert not expired.exists()


class _CountingModel(NamedTuple):
    model: Model
    calls: list[ModelOutput]


def _counting_model(
    monkeypatch: pytest.MonkeyPatch, output: Callable[[], ModelOutput]
) -> _CountingModel:
    """A mockllm model whose provider returns `output()` and records each call."""
    model = get_model("mockllm/model", memoize=False)
    calls: list[ModelOutput] = []

    async def provider_generate(*args: Any, **kwargs: Any) -> ModelOutput:
        calls.append(output())
        return calls[-1]

    monkeypatch.setattr(model.api, "generate", provider_generate)
    return _CountingModel(model, calls)


def _entries(root: Path) -> list[Path]:
    return sorted(root.rglob("*.jsonl"))


def _not_cached_warnings() -> list[str]:
    return [m for m in inspect_logger._warned if "are not cached" in m]


class _PickleSideEffect:
    """Unpickling this creates `marker`."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[Any, ...]:
        return (open, (str(self.marker), "w"))


async def test_cache_never_deserializes_pickle(
    cache_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = tmp_path / "marker"
    payload = pickle.dumps((None, _PickleSideEffect(marker)))

    def no_unpickling(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the cache must not unpickle")

    counting = _counting_model(
        monkeypatch, lambda: ModelOutput.from_content(model="m", content="Hi")
    )
    await counting.model.generate("Hello", cache=True)
    [entry_path] = _entries(cache_root)
    key = entry_path.name.removesuffix(".jsonl")
    planted = [
        entry_path.parent / key,
        entry_path,
        entry_path.parent / "unrelated",
    ]

    monkeypatch.setattr(pickle, "load", no_unpickling)
    monkeypatch.setattr(pickle, "loads", no_unpickling)
    monkeypatch.setattr(pickle, "Unpickler", no_unpickling)

    def plant() -> None:
        for path in planted:
            path.write_bytes(payload)

    plant()
    await counting.model.generate("Hello", cache=True)
    assert len(counting.calls) == 2
    plant()
    assert cache_list_expired() == [planted[0]]
    cache_prune()
    assert not planted[0].exists()

    plant()
    runner = CliRunner()
    result = runner.invoke(cache_command, ["list", "--pruneable"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cache_command, ["prune"])
    assert result.exit_code == 0, result.output
    assert not planted[0].exists()
    assert planted[1].read_bytes() == payload
    assert planted[2].read_bytes() == payload

    assert not marker.exists()


def test_cache_module_does_not_import_pickle():
    """Tripwire: the cache module must never deserialize with pickle."""
    source = Path(cache_module.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {"pickle", "_pickle", "cloudpickle", "dill"} & imported


def _cache_entry_for(content: str) -> CacheEntry:
    return CacheEntry(
        base_url=None,
        config=GenerateConfig(),
        input=[ChatMessageUser(content=content)],
        model="mockllm/model",
        policy=CachePolicy(),
        tool_choice=None,
        tools=[],
    )


def test_cache_round_trip(cache_root: Path):
    output = ModelOutput(
        model="m",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    id="message-id",
                    content=[
                        ContentReasoning(reasoning="thinking", signature="sig"),
                        ContentText(text="Hi"),
                    ],
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            function="f",
                            arguments={"s": "x", "n": None, "l": [1, 2.5, True]},
                        ),
                        ToolCall(
                            id="call-2",
                            function="g",
                            arguments={"a": math.inf, "b": {"c": -math.inf}},
                        ),
                    ],
                ),
                stop_reason="tool_calls",
                logprobs=Logprobs(content=[Logprob(token="Hi", logprob=-math.inf)]),
            )
        ],
        usage=ModelUsage(input_tokens=1, output_tokens=2, total_cost=math.inf),
        time=1.5,
    )
    entry = _cache_entry_for("round trip")
    assert cache_store(entry=entry, output=output) is True
    assert cache_fetch(entry) == output
    assert _not_cached_warnings() == []


def test_cache_round_trip_non_ascii(cache_root: Path):
    text = "Grüße, 你好, привет 🎉"
    output = ModelOutput.from_message(
        ChatMessageAssistant(
            content=text,
            tool_calls=[ToolCall(id="call", function="f", arguments={text: text})],
        )
    )
    entry = _cache_entry_for("non-ascii")
    assert cache_store(entry=entry, output=output) is True
    assert cache_fetch(entry) == output
    [path] = _entries(cache_root)
    body = path.read_bytes().splitlines()[1]
    assert text.encode("utf-8") in body


def _future_header() -> bytes:
    return json.dumps(_header(_FUTURE, "{key}")).encode()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"\x00\xff\x13 not json\n{}\n", id="random-bytes"),
        pytest.param(
            json.dumps(_header(_PAST, "{key}")).encode(), id="header-without-newline"
        ),
        pytest.param(
            json.dumps(_header(_PAST, "{key}", pad="x" * 5000)).encode() + b"\n",
            id="header-over-4k",
        ),
        pytest.param(
            json.dumps(_header(_PAST, "{key}", version=2)).encode() + b"\n",
            id="version-2",
        ),
        pytest.param(
            json.dumps(_header(_PAST, _OTHER_KEY)).encode() + b"\n", id="other-key"
        ),
        pytest.param(
            json.dumps(
                {"version": 1, "key": "{key}", "expiry": "2000-01-01T00:00:00"}
            ).encode()
            + b"\n",
            id="expiry-without-offset",
        ),
    ],
)
async def test_cache_invalid_headers(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
):
    counting = _counting_model(
        monkeypatch, lambda: ModelOutput.from_content(model="m", content="Hi")
    )
    await counting.model.generate("Hello", cache=True)
    [path] = _entries(cache_root)
    key = path.name.removesuffix(".jsonl")
    body = path.read_bytes().splitlines(keepends=True)[1]
    content = content.replace(b"{key}", key.encode())
    if content.endswith(b"\n"):
        content += body
    path.write_bytes(content)

    assert cache_list_expired() == []
    cache_prune()
    cache_prune([path])
    assert path.read_bytes() == content

    await counting.model.generate("Hello", cache=True)
    assert len(counting.calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="missing"),
        pytest.param(b'{"model": "m", "choi', id="truncated"),
        pytest.param(b'{"choices": "not a list"}\n', id="invalid"),
    ],
)
@pytest.mark.parametrize("expired", [False, True])
async def test_cache_invalid_bodies_are_judged_by_header(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch, body: bytes, expired: bool
):
    counting = _counting_model(
        monkeypatch, lambda: ModelOutput.from_content(model="m", content="Hi")
    )
    await counting.model.generate("Hello", cache=True)
    [path] = _entries(cache_root)
    _plant(path, "", expiry=_PAST if expired else _FUTURE, body=body)

    if expired:
        assert cache_list_expired() == [path]
        cache_prune()
        assert not path.exists()
    else:
        assert cache_list_expired() == []
        cache_prune([path])
        assert path.exists()
        await counting.model.generate("Hello", cache=True)
        assert len(counting.calls) == 2


def test_cache_expiry(cache_root: Path):
    entry = _entry("openai/gpt-4")
    path = cache_root / "openai" / "gpt-4" / f"{entry.key}.jsonl"

    # expired: listed, pruned, and a miss that deletes it on lookup
    _plant(path, "expired", expiry=_PAST)
    assert cache_list_expired() == [path]
    cache_prune()
    assert not path.exists()
    _plant(path, "expired", expiry=_PAST)
    assert cache_fetch(entry) is None
    assert not path.exists()

    # unexpired, or never expiring: a hit, neither listed nor pruned
    for expiry in [_FUTURE, None]:
        _plant(path, "fresh", expiry=expiry)
        assert cache_list_expired() == []
        cache_prune([path])
        fetched = cache_fetch(entry)
        assert fetched is not None and fetched.completion == "fresh"


def test_cache_legacy_entries(cache_root: Path):
    entry = _entry("openai/gpt-4")
    legacy = cache_root / "openai" / "gpt-4" / entry.key
    _plant_legacy(legacy, "legacy", expiry=_FUTURE)

    # never used, whatever its expiry; listed and pruned, by model too
    assert cache_fetch(entry) is None
    assert cache_list_expired() == [legacy]
    assert cache_list_expired(["openai/gpt-4"]) == [legacy]
    assert cache_list_expired(["openai/gpt-5"]) == []
    cache_prune([legacy])
    assert not legacy.exists()

    # a key-named file without a pickle header is left alone
    legacy.write_bytes(b"not a pickle")
    assert cache_list_expired() == []
    cache_prune([legacy])
    assert legacy.exists()


@dataclass
class _Point:
    x: int


class _PointModel(BaseModel):
    x: int


_DATE_TOOL = ToolInfo(
    name="f",
    description="A tool with one parameter.",
    parameters=ToolParams(properties={"x": ToolParam(type="string")}),
)


def _output_with_call(call: ToolCall) -> ModelOutput:
    return ModelOutput.from_message(ChatMessageAssistant(content="", tool_calls=[call]))


def _output_with_args(arguments: dict[str, Any]) -> ModelOutput:
    return _output_with_call(ToolCall(id="call", function="f", arguments=arguments))


@pytest.mark.parametrize(
    "output",
    [
        pytest.param(lambda: _output_with_args({"\ud800": 1}), id="surrogate-key"),
        pytest.param(
            lambda: _output_with_call(
                parse_tool_call("call", "f", "2026-01-01", [_DATE_TOOL])
            ),
            id="yaml-date",
        ),
        pytest.param(
            lambda: _output_with_call(
                parse_tool_call("call", "f", '1: first\n"1": second', [_DATE_TOOL])
            ),
            id="yaml-colliding-keys",
        ),
        pytest.param(lambda: _output_with_args({"x": _Point(1)}), id="dataclass"),
        pytest.param(
            lambda: _output_with_args({"x": _PointModel(x=1)}), id="pydantic-model"
        ),
        pytest.param(
            lambda: ModelOutput.from_content(model="m", content="Hi").model_copy(
                update={"metadata": {"x": object()}}
            ),
            id="metadata-object",
        ),
    ],
)
async def test_cache_lossy_outputs_are_not_cached(
    cache_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Callable[[], ModelOutput],
):
    counting = _counting_model(monkeypatch, output)
    first = await counting.model.generate("Hello", cache=True)
    assert first is counting.calls[0]
    assert _entries(cache_root) == []
    await counting.model.generate("Hello", cache=True)
    assert len(counting.calls) == 2
    assert len(_not_cached_warnings()) == 1


def test_cache_nan_output_is_not_stored(cache_root: Path):
    output = ModelOutput.from_content(model="m", content="Hi")
    output.time = math.nan
    assert cache_store(entry=_cache_entry_for("nan"), output=output) is False
    assert _entries(cache_root) == []
    assert len(_not_cached_warnings()) == 1


def _output_with_empty_completion() -> ModelOutput:
    output = ModelOutput.from_content(model="m", content="merged text")
    output.completion = ""
    return output


@pytest.mark.parametrize(
    "output,check",
    [
        pytest.param(
            lambda: ModelOutput.from_content(model="m", content="Hi").model_copy(
                update={"metadata": {"at": datetime(2026, 1, 1, tzinfo=timezone.utc)}}
            ),
            lambda hit: hit.metadata == {"at": "2026-01-01T00:00:00Z"},
            id="datetime-metadata",
        ),
        pytest.param(
            _output_with_empty_completion,
            lambda hit: hit.completion == "merged text",
            id="empty-completion",
        ),
    ],
)
async def test_cache_normalized_outputs_are_cached(
    cache_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Callable[[], ModelOutput],
    check: Callable[[ModelOutput], bool],
):
    counting = _counting_model(monkeypatch, output)
    await counting.model.generate("Hello", cache=True)
    hit = await counting.model.generate("Hello", cache=True)
    assert len(counting.calls) == 1
    assert check(hit)
    assert _not_cached_warnings() == []


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows refuses the rename while a reader holds the entry open",
)
def test_cache_concurrent_writers_and_reader(cache_root: Path):
    # writers and reader share the cache directory through INSPECT_CACHE_DIR
    context = multiprocessing.get_context("spawn")
    writers = [
        context.Process(target=concurrent_cache_writer, args=(letter, 15))
        for letter in ["a", "b"]
    ]
    expected = [concurrent_cache_output(letter) for letter in ["a", "b"]]
    entry = concurrent_cache_entry()
    for writer in writers:
        writer.start()
    try:
        fetches = 0
        while any(writer.is_alive() for writer in writers):
            fetched = cache_fetch(entry)
            if fetched is None and fetches == 0:
                continue  # the first store has not completed yet
            assert fetched in expected
            fetches += 1
    finally:
        for writer in writers:
            writer.join()
    assert [writer.exitcode for writer in writers] == [0, 0]
    assert fetches > 0
    assert cache_fetch(entry) in expected
    assert list(cache_root.rglob(".inspect_tmp_*")) == []


async def test_cache_failed_write_is_skipped(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch
):
    def failing_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cache_module, "atomic_write_bytes", failing_write)
    counting = _counting_model(
        monkeypatch, lambda: ModelOutput.from_content(model="m", content="Hi")
    )
    output = await counting.model.generate("Hello", cache=True)
    assert output.completion == "Hi"
    assert _entries(cache_root) == []


def test_cache_temporary_files_are_not_entries(cache_root: Path):
    temporary = cache_root / "openai" / "gpt-4" / ".inspect_tmp_abc.writing"
    _plant(temporary, "in progress", expiry=_PAST, key=_KEY)
    assert cache_list_expired() == []
    cache_prune([temporary])
    assert temporary.exists()
    assert cache_size() == [("openai/gpt-4", temporary.stat().st_size)]
    assert cache_clear() is True
    assert not temporary.exists()


async def test_cache_path_setup_failures_are_misses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    (tmp_path / "generate").write_text("not a directory")
    counting = _counting_model(
        monkeypatch, lambda: ModelOutput.from_content(model="m", content="Hi")
    )
    for _ in range(2):
        output = await counting.model.generate("Hello", cache=True)
        assert output.completion == "Hi"
    assert len(counting.calls) == 2
