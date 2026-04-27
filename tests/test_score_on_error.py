from typing import Callable

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, generate, solver


@solver
def failing_solver(fail: Callable[[TaskState], bool] = lambda state: True):
    async def solve(state: TaskState, generate: Generate):
        if fail(state):
            raise ValueError("Eval failed!")

        return state

    return solve


@scorer(metrics=[accuracy()])
def constant_incorrect():
    """Score every sample as INCORRECT regardless of state."""

    async def score(state: TaskState, target):  # type: ignore[no-untyped-def]
        return Score(value="I")

    return score


@scorer(metrics=[accuracy()])
def crashes_on_partial_state():
    """Raises if state.output is empty (i.e. the sample errored before generating)."""

    async def score(state: TaskState, target):  # type: ignore[no-untyped-def]
        if state.output is None or not state.output.completion:
            raise RuntimeError("scorer needs a completion to score")
        return Score(value="C")

    return score


def _make_task(
    *,
    samples: int,
    fail: Callable[[TaskState], bool],
    scorer_factory,
):
    dataset = [Sample(input="Say hello.", target="Hello") for _ in range(samples)]
    return Task(
        dataset=dataset,
        solver=[failing_solver(fail), generate()],
        scorer=scorer_factory(),
        fail_on_error=False,
    )


def test_score_on_error_default_excludes_errored_samples():
    """Errored samples drop from both numerator and denominator by default.

    This is the historical behavior #3707 captured. With 5/10 erroring and
    a scorer that returns INCORRECT for everything, the metric reflects only
    the 5 non-errored samples (all incorrect -> accuracy 0.0).
    """
    task = _make_task(
        samples=10,
        fail=lambda state: state.sample_id <= 5,
        scorer_factory=constant_incorrect,
    )
    log = eval(task, model="mockllm/model")[0]

    assert log.status == "success"
    assert log.results is not None
    assert log.results.completed_samples == 5
    assert log.results.total_samples == 10


def test_score_on_error_includes_errored_samples_in_metric():
    """score_on_error=True routes errored samples through the scorer.

    The scorer (which returns INCORRECT here) lands those samples in the
    metric denominator. completed_samples rises from 5 to 10 — the
    inflated-accuracy bug from #3707 is gone.
    """
    task = _make_task(
        samples=10,
        fail=lambda state: state.sample_id <= 5,
        scorer_factory=constant_incorrect,
    )
    log = eval(task, model="mockllm/model", score_on_error=True)[0]

    assert log.status == "success"
    assert log.results is not None
    assert log.results.completed_samples == 10
    assert log.results.total_samples == 10


def test_score_on_error_drops_scorer_that_cant_handle_partial_state():
    """Scorers that raise on partial state are dropped silently.

    A scorer that crashes when state.output is missing (because the sample
    errored before generating) is skipped during score_on_error rather than
    upgraded into a fresh sample error. The sample's primary error stays the
    one reported.
    """
    task = _make_task(
        samples=4,
        fail=lambda state: state.sample_id <= 2,
        scorer_factory=crashes_on_partial_state,
    )
    log = eval(task, model="mockllm/model", score_on_error=True)[0]

    # Errored samples (1, 2) cause the scorer to raise; with score_on_error those
    # samples are skipped at the scorer rather than upgraded to an outer error.
    # Successful samples (3, 4) score normally and land in the denominator.
    assert log.status == "success"
    assert log.results is not None
    assert log.results.total_samples == 4
