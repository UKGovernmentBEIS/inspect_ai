"""Operator-interrupted samples whose scorers also error must not fail or retry the eval."""

import anyio

from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._samples import sample_active
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver


@solver
def operator_interrupting_solver():
    async def solve(state: TaskState, generate: Generate):
        active = sample_active()
        assert active is not None, "expected an active sample"
        active.interrupt("score")
        # interrupt cancels the surrounding scope; sleep_forever guarantees
        # we never return normally — must be cancelled by the interrupt.
        await anyio.sleep_forever()
        return state

    return solve


@scorer(metrics=[accuracy()])
def buggy_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        raise RuntimeError("buggy scorer")

    return score


def test_operator_interrupt_with_scorer_error():
    """Sample is operator-limited (not error-counted), eval succeeds, no retries."""
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=operator_interrupting_solver(),
            scorer=buggy_scorer(),
        ),
        retry_on_error=3,
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert sample.error_retries == []
