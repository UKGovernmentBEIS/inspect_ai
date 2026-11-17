"""Operator-interrupted samples whose scorers also error must not fail or retry the eval."""

import anyio

from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._samples import sample_active
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import background


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


@scorer(metrics=[accuracy()])
def interrupted_while_scoring_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # an operator cancel (per-sample, or the task-level score/error sweep)
        # landing after the solver finished: the run task group has exited,
        # so the interrupt only stamps the sample
        active = sample_active()
        assert active is not None, "expected an active sample"
        active.interrupt("score")
        raise RuntimeError("buggy scorer")

    return score


def test_interrupt_stamped_during_scoring_keeps_scorer_error():
    """An interrupt the solver never saw does not hide a scorer error."""
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            scorer=interrupted_while_scoring_scorer(),
        ),
        model="mockllm/model",
        fail_on_error=False,
    )[0]

    assert log.samples is not None
    sample = log.samples[0]
    assert sample.limit is None
    assert sample.error is not None
    assert "buggy scorer" in sample.error.message


@solver
def operator_cancel_then_background_failure():
    async def solve(state: TaskState, generate: Generate):
        started = anyio.Event()

        async def cleanup_fails() -> None:
            try:
                started.set()
                await anyio.sleep_forever()
            finally:
                raise RuntimeError("background cleanup failed")

        background(cleanup_fails)
        await started.wait()
        active = sample_active()
        assert active is not None, "expected an active sample"
        active.interrupt("cancel")
        await anyio.sleep_forever()
        return state

    return solve


def test_operator_cancel_stays_cancelled_when_an_error_follows():
    """An error after an operator cancel neither fails the eval nor retries."""
    log = eval(
        Task(
            dataset=MemoryDataset([Sample(id=1, input="hi", target="hi")]),
            solver=operator_cancel_then_background_failure(),
            scorer=buggy_scorer(),
        ),
        model="mockllm/model",
        retry_on_error=1,
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert "background cleanup failed" in sample.error.message
    assert sample.error_retries == []
    assert sample.scores is None or sample.scores == {}
