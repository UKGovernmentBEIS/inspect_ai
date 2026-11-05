from pathlib import Path
from typing import Any

import pytest

import inspect_ai.model._model as model_module
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    cache_path,
    get_model,
)
from inspect_ai.model._cache import CacheEntry, cache_store


async def check_output_cache_round_trip(
    model_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Generate twice with `cache=True` and check the second call is a cache hit.

    The first call must reach the provider and write one cache entry inside a
    fresh cache directory; the identical second call must return that output
    with no provider request and no cache write.
    """
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    model = get_model(model_name, config=GenerateConfig(max_tokens=200))

    provider_calls = 0
    provider_generate = model.api.generate

    async def counting_generate(*args: Any, **kwargs: Any) -> Any:
        nonlocal provider_calls
        provider_calls += 1
        return await provider_generate(*args, **kwargs)

    monkeypatch.setattr(model.api, "generate", counting_generate)

    stored: list[str] = []

    def recording_store(entry: CacheEntry, output: ModelOutput) -> bool:
        stored.append(entry.key)
        return cache_store(entry=entry, output=output)

    monkeypatch.setattr(model_module, "cache_store", recording_store)

    input: list[ChatMessage] = [
        ChatMessageUser(content="Reply with the single word: hello")
    ]
    first = await model.generate(input, cache=True)
    assert first.completion
    assert provider_calls == 1
    assert len(stored) == 1
    assert (cache_path(str(model)) / stored[0]).is_file()

    second = await model.generate(input, cache=True)
    assert provider_calls == 1
    assert len(stored) == 1
    assert second.completion == first.completion
