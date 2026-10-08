import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest
from test_helpers.utils import run_example

from inspect_ai import Task, eval
from inspect_ai._eval.evalset import GENERATE_CONFIG_FIELDS_TO_EXCLUDE
from inspect_ai._util import appdirs
from inspect_ai._util import logger as inspect_logger
from inspect_ai._util.content import ContentText
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    CachePolicy,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
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
    cache_path,
    cache_prune,
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


def _plant(path: Path, content: str, expiry: datetime | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump((expiry, ModelOutput.from_content(model="m", content=content)), f)


_PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_cache_store_and_fetch_stay_in_cache_dir(cache_root: Path, tmp_path: Path):
    entry = _entry(_ESCAPING_MODEL)
    outside = tmp_path / "a" / "b" / "x" / entry.key

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

    # an entry file that is a symlink out of the cache
    entry = _entry("openai/gpt-4")
    target = outside / "entry"
    _plant(target, "planted", expiry=_PAST)
    link = cache_path("openai/gpt-4") / entry.key
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert cache_fetch(entry) is None
    assert cache_list_expired() == []
    assert target.exists()


def test_cache_clear_list_and_prune_stay_in_cache_dir(cache_root: Path, tmp_path: Path):
    outside = tmp_path / "a" / "b" / "x"
    _plant(outside / "expired", "planted", expiry=_PAST)
    before = _files_outside(cache_root, tmp_path)

    assert cache_clear(_ESCAPING_MODEL) is False
    assert cache_list_expired([_ESCAPING_MODEL]) == []
    cache_prune([outside / "expired"])
    assert _files_outside(cache_root, tmp_path) == before


def test_cache_layout_unchanged_for_normal_model_names(cache_root: Path):
    # entries written before this change (same path, same pickle format) are
    # still read, so existing caches keep hitting
    entry = _entry("openai/gpt-4")
    _plant(cache_root / "openai" / "gpt-4" / entry.key, "existing", expiry=None)
    fetched = cache_fetch(entry)
    assert fetched is not None and fetched.completion == "existing"

    # a fresh store lands in the same place and round-trips
    entry = _entry("hf/org/Model-1.5:8b")
    output = ModelOutput.from_content(model="m", content="Hi")
    assert cache_store(entry=entry, output=output) is True
    assert (cache_root / "hf" / "org" / "Model-1.5:8b" / entry.key).is_file()
    fetched = cache_fetch(entry)
    assert fetched is not None and fetched.completion == "Hi"

    # clear, list and prune still work by model name
    _plant(cache_root / "openai" / "gpt-4" / "old", "old", expiry=_PAST)
    expired = cache_list_expired(["openai/gpt-4"])
    assert expired == [cache_root / "openai" / "gpt-4" / "old"]
    cache_prune(expired)
    assert not expired[0].exists()
    assert cache_clear("openai/gpt-4") is True
    assert not (cache_root / "openai" / "gpt-4").exists()
    assert inspect_logger._warned == []


def test_cache_refusals_create_nothing(absent_cache_root: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    _plant(outside, "planted", expiry=_PAST)

    entry = _entry(_ESCAPING_MODEL)
    output = ModelOutput.from_content(model="m", content="Hi")
    with pytest.raises(ValueError):
        cache_path(_ESCAPING_MODEL)
    assert cache_store(entry=entry, output=output) is False
    assert cache_fetch(entry) is None
    assert cache_clear(_ESCAPING_MODEL) is False
    assert cache_list_expired([_ESCAPING_MODEL]) == []
    cache_prune([outside])
    assert list(tmp_path.iterdir()) == [outside]

    # the fixture does point the cache here: an accepted lookup creates it
    assert cache_path() == absent_cache_root
    assert absent_cache_root.is_dir()


def test_cache_prune_skips_unresolvable_paths(cache_root: Path):
    expired = cache_root / "openai" / "gpt-4" / "old"
    _plant(expired, "old", expiry=_PAST)
    cache_prune([Path("invalid\0path"), expired])
    assert not expired.exists()
