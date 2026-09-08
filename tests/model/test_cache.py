from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_helpers.utils import run_example

from inspect_ai import Task, eval
from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    CachePolicy,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.model._cache import (
    _CACHE_KEY_DROPPED_FIELDS,
    _CACHE_KEY_NEUTRALIZED_FIELDS,
    CacheEntry,
    _cache_key_config,
    cache_fetch,
    cache_store,
)
from inspect_ai.solver import generate


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


def test_cache_key_neutral_fields_match_task_identity():
    """The cache key and task identity must agree on which config fields are inert.

    Both answer the same question — can this field change what the provider
    returns — so a field classified for one and not the other is a bug in
    whichever list was missed. `attempt_timeout` and `cache_prompt` were part
    of the cache key for exactly that reason.
    """
    assert (
        _CACHE_KEY_DROPPED_FIELDS | _CACHE_KEY_NEUTRALIZED_FIELDS
    ) == GENERATE_CONFIG_FIELDS_TO_EXCLUDE, (
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
