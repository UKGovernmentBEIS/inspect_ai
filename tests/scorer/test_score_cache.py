"""Tests for score output caching (scorer/_cache.py and _eval/score.py integration)."""

import os
import pathlib
import pickle
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from inspect_ai._eval.score import _run_score_task, score_async
from inspect_ai.log import EvalLog
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalPlanStep,
    EvalSample,
    EvalSpec,
)
from inspect_ai.model import ChatCompletionChoice, GenerateConfig, ModelOutput
from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.scorer import accuracy
from inspect_ai.scorer._cache import (
    ScoreCacheEntry,
    _canonical,
    _score_cache_key,
    score_cache_clear,
    score_cache_fetch,
    score_cache_path,
    score_cache_size,
    score_cache_store,
)
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache_entry(**overrides: object) -> ScoreCacheEntry:
    """Create a ScoreCacheEntry with sensible defaults, overridable per-field."""
    defaults = dict(
        scorer_name="match",
        scorer_args={"template": "default"},
        eval_model="mockllm/model",
        model_roles=None,
        input="What is 2+2?",
        messages=['{"role":"user","content":"What is 2+2?"}'],
        output='{"choices":[]}',
        target="4",
        choices=None,
        metadata=None,
        policy=CachePolicy(),
        epoch=1,
    )
    defaults.update(overrides)
    return ScoreCacheEntry(**defaults)


def _make_log_header(**overrides: object) -> EvalLog:
    """Create a minimal EvalLog header for testing."""
    defaults = dict(
        version=2,
        status="success",
        eval=EvalSpec(
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test",
            run_id="test-run",
            dataset=EvalDataset(),
            model="mockllm/model",
            config=EvalConfig(),
        ),
        plan=EvalPlan(
            name="test",
            steps=[EvalPlanStep(solver="generate")],
            config=GenerateConfig(),
        ),
    )
    defaults.update(overrides)
    return EvalLog(**defaults)


def _make_sample(
    id: str = "test-1",
    input: str = "What is 2+2?",
    target: str = "4",
    output_text: str = "4",
) -> EvalSample:
    return EvalSample(
        id=id,
        epoch=1,
        input=input,
        target=target,
        messages=[ChatMessageUser(role="user", content=input)],
        output=ModelOutput(
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(role="assistant", content=output_text)
                )
            ]
        ),
    )


@scorer(metrics=[accuracy()])
def _always_correct() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1.0)

    return score


@scorer(metrics=[accuracy()])
def _always_wrong() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=0.0)

    return score


# Track how many times the scorer is actually invoked
_call_count = 0


@scorer(metrics=[accuracy()])
def _counting_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        global _call_count
        _call_count += 1
        return Score(value=1.0)

    return score


# ---------------------------------------------------------------------------
# Unit tests: _canonical helper
# ---------------------------------------------------------------------------


class TestCanonical:
    def test_dict_ordering_independent(self):
        """Dicts with same keys in different order produce same canonical form."""
        assert _canonical({"b": 2, "a": 1}) == _canonical({"a": 1, "b": 2})

    def test_nested_dict_ordering(self):
        assert _canonical({"x": {"b": 2, "a": 1}}) == _canonical(
            {"x": {"a": 1, "b": 2}}
        )

    def test_non_serializable_falls_back_to_str(self):
        """Non-JSON-serializable objects use str() fallback."""
        result = _canonical(object())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit tests: cache key
# ---------------------------------------------------------------------------


class TestScoreCacheKey:
    def test_same_inputs_same_key(self):
        entry1 = _make_cache_entry()
        entry2 = _make_cache_entry()
        assert _score_cache_key(entry1) == _score_cache_key(entry2)

    def test_different_scorer_name(self):
        entry1 = _make_cache_entry(scorer_name="match")
        entry2 = _make_cache_entry(scorer_name="f1")
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_scorer_args(self):
        entry1 = _make_cache_entry(scorer_args={"template": "a"})
        entry2 = _make_cache_entry(scorer_args={"template": "b"})
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_eval_model(self):
        entry1 = _make_cache_entry(eval_model="openai/gpt-4")
        entry2 = _make_cache_entry(eval_model="anthropic/claude-3")
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_model_roles(self):
        entry1 = _make_cache_entry(model_roles={"grader": "openai/gpt-4"})
        entry2 = _make_cache_entry(model_roles={"grader": "openai/gpt-3.5"})
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_target(self):
        entry1 = _make_cache_entry(target="4")
        entry2 = _make_cache_entry(target="5")
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_input(self):
        entry1 = _make_cache_entry(input="What is 2+2?")
        entry2 = _make_cache_entry(input="What is 3+3?")
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_output(self):
        entry1 = _make_cache_entry(output='{"answer":"4"}')
        entry2 = _make_cache_entry(output='{"answer":"5"}')
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_metadata(self):
        entry1 = _make_cache_entry(metadata={"difficulty": "easy"})
        entry2 = _make_cache_entry(metadata={"difficulty": "hard"})
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_choices(self):
        entry1 = _make_cache_entry(choices=["A", "B", "C"])
        entry2 = _make_cache_entry(choices=["X", "Y", "Z"])
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_different_scopes(self):
        entry1 = _make_cache_entry(policy=CachePolicy(scopes={"v": "1"}))
        entry2 = _make_cache_entry(policy=CachePolicy(scopes={"v": "2"}))
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_epoch_included_when_per_epoch(self):
        entry1 = _make_cache_entry(epoch=1, policy=CachePolicy(per_epoch=True))
        entry2 = _make_cache_entry(epoch=2, policy=CachePolicy(per_epoch=True))
        assert _score_cache_key(entry1) != _score_cache_key(entry2)

    def test_epoch_ignored_when_not_per_epoch(self):
        entry1 = _make_cache_entry(epoch=1, policy=CachePolicy(per_epoch=False))
        entry2 = _make_cache_entry(epoch=2, policy=CachePolicy(per_epoch=False))
        assert _score_cache_key(entry1) == _score_cache_key(entry2)

    def test_expiry_not_in_key(self):
        """Different expiry durations should NOT produce different keys."""
        entry1 = _make_cache_entry(policy=CachePolicy(expiry="1W"))
        entry2 = _make_cache_entry(policy=CachePolicy(expiry="1D"))
        assert _score_cache_key(entry1) == _score_cache_key(entry2)

    def test_dict_ordering_independent(self):
        """scorer_args dict ordering should not affect key."""
        entry1 = _make_cache_entry(scorer_args={"a": 1, "b": 2})
        entry2 = _make_cache_entry(scorer_args={"b": 2, "a": 1})
        assert _score_cache_key(entry1) == _score_cache_key(entry2)


# ---------------------------------------------------------------------------
# Unit tests: store and fetch
# ---------------------------------------------------------------------------


class TestScoreCacheStoreAndFetch:
    @pytest.fixture(autouse=True)
    def _use_tmp_cache(self, tmp_path: pathlib.Path):
        """Redirect score cache to a temp directory for test isolation."""
        with patch.dict(os.environ, {"INSPECT_CACHE_DIR": str(tmp_path)}):
            yield

    def test_round_trip(self):
        entry = _make_cache_entry()
        score = Score(value=0.75, answer="4", explanation="Correct!")
        assert score_cache_store(entry, score) is True

        fetched = score_cache_fetch(entry)
        assert fetched is not None
        assert fetched.value == 0.75
        assert fetched.answer == "4"
        assert fetched.explanation == "Correct!"

    def test_cache_miss(self):
        entry = _make_cache_entry(scorer_name="nonexistent")
        assert score_cache_fetch(entry) is None

    def test_different_entries_dont_collide(self):
        entry1 = _make_cache_entry(target="4")
        entry2 = _make_cache_entry(target="5")
        score1 = Score(value=1.0)
        score2 = Score(value=0.0)

        score_cache_store(entry1, score1)
        score_cache_store(entry2, score2)

        assert score_cache_fetch(entry1).value == 1.0
        assert score_cache_fetch(entry2).value == 0.0

    def test_expired_entry_returns_none(self):
        entry = _make_cache_entry(policy=CachePolicy(expiry="1s"))
        score = Score(value=1.0)
        score_cache_store(entry, score)

        # Patch the expiry to be in the past
        cache_file = score_cache_path(scorer_name=entry.scorer_name) / _score_cache_key(
            entry
        )
        with open(cache_file, "rb") as f:
            _, stored_score = pickle.load(f)
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        with open(cache_file, "wb") as f:
            pickle.dump((expired_time, stored_score), f)

        assert score_cache_fetch(entry) is None

    def test_none_expiry_never_expires(self):
        entry = _make_cache_entry(policy=CachePolicy(expiry=None))
        score = Score(value=1.0)
        score_cache_store(entry, score)
        assert score_cache_fetch(entry) is not None

    def test_score_with_metadata(self):
        entry = _make_cache_entry()
        score = Score(value=1.0, metadata={"key": "value", "nested": {"a": 1}})
        score_cache_store(entry, score)

        fetched = score_cache_fetch(entry)
        assert fetched is not None
        assert fetched.metadata == {"key": "value", "nested": {"a": 1}}

    def test_non_serializable_metadata_returns_false(self):
        """Score with non-picklable metadata should fail gracefully."""
        entry = _make_cache_entry()
        score = Score(value=1.0, metadata={"func": lambda x: x})
        result = score_cache_store(entry, score)
        # Should return False (not crash)
        assert result is False

    def test_clear(self):
        entry = _make_cache_entry()
        score_cache_store(entry, Score(value=1.0))
        assert score_cache_fetch(entry) is not None

        score_cache_clear()
        assert score_cache_fetch(entry) is None

    def test_clear_specific_scorer(self):
        entry1 = _make_cache_entry(scorer_name="match")
        entry2 = _make_cache_entry(scorer_name="f1")
        score_cache_store(entry1, Score(value=1.0))
        score_cache_store(entry2, Score(value=0.5))

        score_cache_clear(scorer_name="match")
        assert score_cache_fetch(entry1) is None
        assert score_cache_fetch(entry2) is not None

    def test_cache_size(self):
        entry = _make_cache_entry()
        score_cache_store(entry, Score(value=1.0))

        sizes = score_cache_size()
        assert len(sizes) > 0
        assert all(size > 0 for _, size in sizes)

    def test_atomic_write_creates_valid_file(self):
        """Verify atomic write produces a valid pickle file."""
        entry = _make_cache_entry()
        score = Score(value=0.42)
        score_cache_store(entry, score)

        cache_file = score_cache_path(scorer_name=entry.scorer_name) / _score_cache_key(
            entry
        )
        assert cache_file.exists()
        with open(cache_file, "rb") as f:
            expiry, loaded_score = pickle.load(f)
        assert isinstance(loaded_score, Score)
        assert loaded_score.value == 0.42
        assert expiry is not None  # default policy has 1W expiry


# ---------------------------------------------------------------------------
# Integration tests: _run_score_task with caching
# ---------------------------------------------------------------------------


class TestRunScoreTaskWithCache:
    @pytest.fixture(autouse=True)
    def _use_tmp_cache(self, tmp_path: pathlib.Path):
        with patch.dict(os.environ, {"INSPECT_CACHE_DIR": str(tmp_path)}):
            yield

    @pytest.fixture
    def log_header(self) -> EvalLog:
        return _make_log_header()

    @pytest.fixture
    def sample(self) -> EvalSample:
        return _make_sample()

    async def test_cache_hit_skips_scorer(self, log_header, sample):
        """Second call with same inputs should use cache, not invoke scorer."""
        global _call_count
        _call_count = 0

        scorer_instance = _counting_scorer()
        policy = CachePolicy()

        # First call: scorer runs
        results1, _ = await _run_score_task(
            log_header, sample, [scorer_instance], "overwrite", policy
        )
        assert _call_count == 1
        assert "_counting_scorer" in results1

        # Reset sample events for second call (simulate fresh re-score)
        sample.events = []
        sample.scores = {}

        # Second call: should hit cache
        results2, _ = await _run_score_task(
            log_header, sample, [scorer_instance], "overwrite", policy
        )
        assert _call_count == 1  # Not incremented — cache hit
        assert "_counting_scorer" in results2
        assert results2["_counting_scorer"].score.value == 1.0

    async def test_score_event_emitted_on_cache_hit(self, log_header, sample):
        """ScoreEvent should appear in transcript even on cache hit."""
        from inspect_ai.event._score import ScoreEvent

        scorer_instance = _always_correct()
        policy = CachePolicy()

        # Populate cache
        await _run_score_task(
            log_header, sample, [scorer_instance], "overwrite", policy
        )

        # Reset for second call
        sample.events = []
        sample.scores = {}

        # Second call — cache hit
        await _run_score_task(
            log_header, sample, [scorer_instance], "overwrite", policy
        )

        score_events = [e for e in sample.events if isinstance(e, ScoreEvent)]
        assert len(score_events) == 1
        assert score_events[0].score.value == 1.0

    async def test_no_cache_when_disabled(self, log_header, sample):
        """Without cache_policy, scorer always runs."""
        global _call_count
        _call_count = 0

        scorer_instance = _counting_scorer()

        await _run_score_task(log_header, sample, [scorer_instance], "overwrite", None)
        assert _call_count == 1

        sample.events = []
        sample.scores = {}

        await _run_score_task(log_header, sample, [scorer_instance], "overwrite", None)
        assert _call_count == 2  # Runs again without caching

    def test_different_model_roles_different_cache_key(self):
        """Different model_roles should produce different cache keys."""
        entry1 = _make_cache_entry(model_roles=None)
        entry2 = _make_cache_entry(model_roles={"grader": "openai/gpt-4"})

        score_cache_store(entry1, Score(value=1.0))
        score_cache_store(entry2, Score(value=0.5))

        # Each entry should fetch its own cached score
        assert score_cache_fetch(entry1).value == 1.0
        assert score_cache_fetch(entry2).value == 0.5

    def test_non_registry_scorer_as_scorer_spec_raises(self):
        """as_scorer_spec on a non-registry scorer raises PrerequisiteError.

        This is caught in _run_score_task to fall back to uncached execution.
        """
        from inspect_ai._util.error import PrerequisiteError
        from inspect_ai.scorer._scorer import as_scorer_spec

        async def plain_scorer(state: TaskState, target: Target) -> Score:
            return Score(value=0.5)

        with pytest.raises(PrerequisiteError):
            as_scorer_spec(plain_scorer)


# ---------------------------------------------------------------------------
# Integration test: score_async with cache
# ---------------------------------------------------------------------------


class TestScoreAsyncWithCache:
    @pytest.fixture(autouse=True)
    def _use_tmp_cache(self, tmp_path: pathlib.Path):
        with patch.dict(os.environ, {"INSPECT_CACHE_DIR": str(tmp_path)}):
            yield

    async def test_score_async_cache_round_trip(self):
        """score_async with cache=True should cache and reuse scores."""
        global _call_count
        _call_count = 0

        log = _make_log_header()
        log.samples = [_make_sample(id="s1"), _make_sample(id="s2")]

        scorer_instance = _counting_scorer()

        # First score: all scorers run
        scored_log = await score_async(
            log=log,
            scorers=[scorer_instance],
            action="overwrite",
            cache=True,
            copy=True,
        )
        assert _call_count == 2  # 2 samples scored
        assert scored_log.results is not None

        # Second score: should hit cache for all samples
        _call_count = 0
        scored_log2 = await score_async(
            log=log,
            scorers=[scorer_instance],
            action="overwrite",
            cache=True,
            copy=True,
        )
        assert _call_count == 0  # All cache hits
        assert scored_log2.results is not None

    async def test_score_async_cache_policy_custom_expiry(self):
        """Custom CachePolicy with specific expiry should work."""
        log = _make_log_header()
        log.samples = [_make_sample()]

        scored_log = await score_async(
            log=log,
            scorers=[_always_correct()],
            action="overwrite",
            cache=CachePolicy(expiry="1D"),
            copy=True,
        )
        assert scored_log.results is not None

    async def test_score_async_no_cache_default(self):
        """cache=False (default) should not cache."""
        global _call_count
        _call_count = 0

        log = _make_log_header()
        log.samples = [_make_sample()]

        await score_async(
            log=log,
            scorers=[_counting_scorer()],
            action="overwrite",
            cache=False,
            copy=True,
        )
        assert _call_count == 1

        await score_async(
            log=log,
            scorers=[_counting_scorer()],
            action="overwrite",
            cache=False,
            copy=True,
        )
        assert _call_count == 2  # Scorer ran again
