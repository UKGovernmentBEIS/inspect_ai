from typing import Any, cast

import pytest

from inspect_ai.arena import ArenaState, JudgeVerdict, Winner, pairwise_scorer
from inspect_ai.model import ModelName
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState


def _make_state(input_text: str, responses: dict[str, str]) -> TaskState:
    state = TaskState(
        model=ModelName("openai/gpt-4o"),
        sample_id="s1",
        epoch=1,
        input=input_text,
        messages=[],
    )
    arena = state.store_as(ArenaState)
    arena.responses = dict(responses)
    return state


def _stub_judge(verdicts: dict[tuple[str, str], Winner]):
    """Return a Judge that picks winners from a pre-populated lookup."""

    async def judge(prompt: str, response_a: str, response_b: str) -> JudgeVerdict:
        # We map by the response strings since our state uses names as values.
        return JudgeVerdict(winner=verdicts[(response_a, response_b)])

    return judge


async def test_pairwise_scorer_generates_all_pairs() -> None:
    state = _make_state(
        "the question",
        {"A": "ra", "B": "rb", "C": "rc"},
    )

    # 3 contestants → 3 pairs in combinations() order: (A,B), (A,C), (B,C)
    # Verdicts in pair-local "a"/"b" positions:
    #   (A,B) winner=a → A wins
    #   (A,C) winner=tie
    #   (B,C) winner=a → B wins
    judge = _stub_judge(
        {
            ("ra", "rb"): "a",
            ("ra", "rc"): "tie",
            ("rb", "rc"): "a",
        }
    )

    scorer = pairwise_scorer(judge)
    score = await scorer(state, Target(""))
    assert score is not None

    metadata = score.metadata or {}
    comparisons = metadata["comparisons"]
    assert comparisons == [
        {"a": "A", "b": "B", "winner": "a"},
        {"a": "A", "b": "C", "winner": "tie"},
        {"a": "B", "b": "C", "winner": "a"},
    ]

    # value carries per-contestant win points for this sample:
    # A: 1 (vs B) + 0.5 (tie vs C) = 1.5
    # B: 1 (vs C)                  = 1.0
    # C: 0.5 (tie vs A)            = 0.5
    value = cast(dict[str, Any], score.value)
    assert value == {"A": 1.5, "B": 1.0, "C": 0.5}


async def test_pairwise_scorer_with_one_contestant_returns_empty() -> None:
    state = _make_state("q", {"only": "response"})

    # Should not raise even though no pair exists; judge must not be called.
    async def boom(*args: object, **kwargs: object) -> JudgeVerdict:
        pytest.fail("judge should not be invoked when fewer than 2 contestants")

    scorer = pairwise_scorer(boom)
    score = await scorer(state, Target(""))
    assert score is not None

    metadata = score.metadata or {}
    assert metadata["comparisons"] == []
    assert score.value == {"only": 0.0}


async def test_pairwise_scorer_surfaces_failed_contestants() -> None:
    state = _make_state("q", {"A": "ra", "B": "rb"})
    arena = state.store_as(ArenaState)
    arena.failed = ["C", "D"]

    judge = _stub_judge({("ra", "rb"): "a"})
    scorer = pairwise_scorer(judge)
    score = await scorer(state, Target(""))
    assert score is not None

    metadata = score.metadata or {}
    assert metadata["failed"] == ["C", "D"]
