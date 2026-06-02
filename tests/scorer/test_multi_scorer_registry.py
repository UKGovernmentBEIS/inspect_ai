"""Regression tests for multi_scorer() registry fix.

Issue: https://github.com/UKGovernmentBEIS/inspect_ai/issues/4027

Before the fix, multi_scorer() returned an unregistered closure. Any call that
went through Inspect's scorer dispatch loop (which calls registry_info() on every
scorer) would crash with:

    PrerequisiteError: Object score does not have registry info

These tests verify the fix without requiring any LLM calls.
"""

import pytest

from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.scorer import Scorer, mean, scorer
from inspect_ai.scorer._metric import CORRECT, Score
from inspect_ai.scorer._multi import multi_scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState


# ---------------------------------------------------------------------------
# Minimal stub scorer — no LLM, always returns CORRECT
# ---------------------------------------------------------------------------

@scorer(metrics=[mean()])
def _always_correct() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT, answer="stub")

    return score


@scorer(metrics=[mean()])
def _always_incorrect() -> Scorer:
    from inspect_ai.scorer._metric import INCORRECT

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=INCORRECT, answer="stub")

    return score


# ---------------------------------------------------------------------------
# Registry tests (the core regression — no LLM required)
# ---------------------------------------------------------------------------

class TestMultiScorerRegistryInfo:
    """multi_scorer() must return a scorer with registry info attached.

    These tests fail on the unfixed code and pass after the fix.
    """

    def test_is_registry_object(self) -> None:
        """multi_scorer result must be a registry object."""
        ms = multi_scorer([_always_correct(), _always_correct()], reducer="mean")
        assert is_registry_object(ms), (
            "multi_scorer() returned an unregistered closure — "
            "Inspect's scorer dispatch will crash with "
            "'Object score does not have registry info'."
        )

    def test_registry_type_is_scorer(self) -> None:
        """Registry type must be 'scorer'."""
        ms = multi_scorer([_always_correct()], reducer="mean")
        info = registry_info(ms)
        assert info.type == "scorer"

    def test_registry_name_is_multi_scorer(self) -> None:
        """Registry name must be 'multi_scorer'."""
        ms = multi_scorer([_always_correct()], reducer="mean")
        info = registry_info(ms)
        assert info.name == "multi_scorer"

    def test_registry_metadata_has_metrics_key(self) -> None:
        """Registry metadata must contain the SCORER_METRICS key."""
        from inspect_ai.scorer._scorer import SCORER_METRICS

        ms = multi_scorer([_always_correct()], reducer="mean")
        info = registry_info(ms)
        assert SCORER_METRICS in info.metadata

    @pytest.mark.parametrize("reducer", ["mean", "mode", "median"])
    def test_all_reducers_produce_registered_scorer(self, reducer: str) -> None:
        """Each built-in reducer string must produce a registered scorer."""
        ms = multi_scorer([_always_correct(), _always_incorrect()], reducer=reducer)
        assert is_registry_object(ms), f"reducer={reducer!r} produced unregistered scorer"

    def test_two_calls_both_registered(self) -> None:
        """Each call to multi_scorer() must produce an independently registered scorer."""
        ms1 = multi_scorer([_always_correct()], reducer="mean")
        ms2 = multi_scorer([_always_incorrect()], reducer="mode")
        assert is_registry_object(ms1)
        assert is_registry_object(ms2)

    def test_empty_scorers_raises(self) -> None:
        """multi_scorer([]) should raise ValueError, not crash elsewhere."""
        with pytest.raises(ValueError, match="at least one scorer"):
            multi_scorer([], reducer="mean")


# ---------------------------------------------------------------------------
# Functional test — runs the scorer pipeline in-process, no network
# ---------------------------------------------------------------------------

class TestMultiScorerFunctional:
    """Verify multi_scorer actually aggregates scores correctly."""

    @pytest.mark.asyncio
    async def test_mean_of_correct_and_incorrect(self) -> None:
        """mean([CORRECT, INCORRECT]) should produce a numeric score of 0.5."""
        from inspect_ai.dataset import Sample
        from inspect_ai.solver._task_state import TaskState
        from inspect_ai.model._chat_message import ChatMessageAssistant

        state = TaskState(
            model="stub/stub",
            sample_id=1,
            epoch=1,
            input="What is 2 + 2?",
            messages=[ChatMessageAssistant(content="4")],
        )
        target = Target("4")

        ms = multi_scorer(
            [_always_correct(), _always_incorrect()],
            reducer="mean",
        )
        result = await ms(state, target)

        assert result is not None
        assert result.as_float() == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_mode_of_two_correct_one_incorrect(self) -> None:
        """mode([CORRECT, CORRECT, INCORRECT]) should pick CORRECT (1.0)."""
        from inspect_ai.solver._task_state import TaskState
        from inspect_ai.model._chat_message import ChatMessageAssistant

        state = TaskState(
            model="stub/stub",
            sample_id=1,
            epoch=1,
            input="Q",
            messages=[ChatMessageAssistant(content="A")],
        )
        target = Target("A")

        ms = multi_scorer(
            [_always_correct(), _always_correct(), _always_incorrect()],
            reducer="mode",
        )
        result = await ms(state, target)

        assert result is not None
        assert result.as_float() == pytest.approx(1.0)
