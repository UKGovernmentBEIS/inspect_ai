import random
from pathlib import Path
from typing import Sequence

import anyio
import pytest
from test_helpers.utils import failing_solver_deterministic, skip_if_github_action

from inspect_ai import Task, eval, eval_async
from inspect_ai._util.asyncfiles import AsyncFilesystem, get_async_filesystem
from inspect_ai.dataset import Sample, example_dataset
from inspect_ai.log import read_eval_log, read_eval_log_async, transcript
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.solver._prompt import system_message
from inspect_ai.util import CheckpointConfig, checkpointer


@pytest.mark.parametrize("checkpoint", [None, True, False])
def test_retry_on_error(checkpoint: bool | None) -> None:
    task = Task(
        solver=failing_solver_deterministic([True, False]), checkpoint=checkpoint
    )
    log = eval(task, retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error_retries is not None
    assert len(log.samples[0].error_retries) == 1


async def test_retry_on_error_checkpoint_without_filesystem_context() -> None:
    log = (
        await eval_async(
            Task(solver=failing_solver_deterministic([True, False]), checkpoint=True),
            model="mockllm/model",
            retry_on_error=1,
        )
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is None
    assert log.samples[0].error_retries is not None
    assert len(log.samples[0].error_retries) == 1


async def test_retry_checkpoint_lookup_error_is_sample_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups = 0

    async def failed_lookup(
        eval_checkpoints_dir: str | None, sample_id: int | str, epoch: int
    ) -> None:
        nonlocal lookups
        lookups += 1
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(
        "inspect_ai._eval.task.run.resolve_resume_checkpoint", failed_lookup
    )

    @solver
    def fail_sample() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "failed":
                raise RuntimeError("solver failed")
            return state

        return solve

    log = (
        await eval_async(
            Task(
                dataset=[
                    Sample(id="failed", input="fail"),
                    Sample(id="ok", input="ok"),
                ],
                solver=fail_sample(),
                checkpoint=True,
            ),
            model="mockllm/model",
            retry_on_error=1,
            fail_on_error=False,
        )
    )[0]
    assert lookups == 1
    assert log.status == "success"
    assert log.samples is not None
    samples = {sample.id: sample for sample in log.samples}
    assert samples["ok"].error is None
    assert samples["failed"].error is not None
    assert "checkpoint storage unavailable" in samples["failed"].error.message
    assert samples["failed"].error_retries is not None
    assert len(samples["failed"].error_retries) == 1


async def test_retry_checkpoint_lookup_cancellation_closes_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup_started = anyio.Event()
    closed = anyio.Event()
    lookup_filesystems: list[AsyncFilesystem] = []
    original_close = AsyncFilesystem.close

    async def blocked_lookup(
        eval_checkpoints_dir: str | None, sample_id: int | str, epoch: int
    ) -> None:
        lookup_filesystems.append(get_async_filesystem())
        lookup_started.set()
        await anyio.sleep_forever()

    async def tracked_close(self: AsyncFilesystem) -> None:
        if lookup_filesystems and self is lookup_filesystems[0]:
            await anyio.lowlevel.checkpoint()
            closed.set()
        await original_close(self)

    monkeypatch.setattr(
        "inspect_ai._eval.task.run.resolve_resume_checkpoint", blocked_lookup
    )
    monkeypatch.setattr(AsyncFilesystem, "close", tracked_close)

    async def run_eval() -> None:
        await eval_async(
            Task(solver=failing_solver_deterministic([True, False]), checkpoint=True),
            model="mockllm/model",
            retry_on_error=1,
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_eval)
        await lookup_started.wait()
        tg.cancel_scope.cancel()
    assert closed.is_set()
    with pytest.raises(RuntimeError, match="No AsyncFilesystem is available"):
        get_async_filesystem()


@pytest.mark.slow
async def test_retry_on_error_resumes_latest_checkpoint(tmp_path: Path) -> None:
    entered_turns: list[int] = []

    @solver
    def checkpoint_then_fail() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            async with checkpointer() as cp:
                turn = cp.track("turn", lambda: turn, 0)
                entered_turns.append(turn)
                if turn < 2:
                    turn += 1
                    await cp.checkpoint()
                    raise RuntimeError("failure after checkpoint")
            return state

        return solve

    task = Task(
        solver=checkpoint_then_fail(),
        checkpoint=CheckpointConfig(checkpoints_location=str(tmp_path / "checkpoints")),
    )
    log = (
        await eval_async(
            task,
            model="mockllm/model",
            retry_on_error=2,
            log_dir=str(tmp_path / "logs"),
        )
    )[0]
    assert entered_turns == [0, 1, 2]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is None
    assert log.samples[0].error_retries is not None
    assert len(log.samples[0].error_retries) == 2
    persisted = await read_eval_log_async(log.location)
    assert persisted.samples is not None
    assert persisted.samples[0].error_retries == log.samples[0].error_retries


@pytest.mark.slow
async def test_retry_on_error_resumes_for_scoring(tmp_path: Path) -> None:
    attempts: list[str] = []
    agent_runs = 0
    scoring_runs = 0

    @solver
    def checkpointed_agent() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            nonlocal agent_runs
            async with checkpointer() as cp:
                attempts.append(cp.attempt)
                if cp.attempt != "resume_for_scoring":
                    agent_runs += 1
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def failing_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            nonlocal scoring_runs
            scoring_runs += 1
            if scoring_runs < 3:
                raise RuntimeError("scoring failed")
            return Score(value=1)

        return score

    log = (
        await eval_async(
            Task(
                solver=checkpointed_agent(),
                scorer=failing_scorer(),
                checkpoint=True,
            ),
            model="mockllm/model",
            retry_on_error=2,
            log_dir=str(tmp_path / "logs"),
        )
    )[0]
    assert log.status == "success"
    assert attempts == ["initial", "resume_for_scoring", "resume_for_scoring"]
    assert agent_runs == 1
    assert scoring_runs == 3
    assert log.samples is not None
    assert log.samples[0].error is None
    assert log.samples[0].error_retries is not None
    assert len(log.samples[0].error_retries) == 2


def test_no_retry_on_error():
    task = Task(solver=failing_solver_deterministic([True, False]))
    log = eval(task, fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is not None
    assert len(log.samples[0].error_retries) == 0


def test_retry_on_error_state():
    task = Task(
        solver=[
            system_message("do your best!"),
            failing_solver_deterministic([True, False]),
        ]
    )
    log = eval(task, retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples[0].messages) == 2


def test_retry_on_error_then_fail():
    task = Task(solver=failing_solver_deterministic([True, True, True, True]))
    log = eval(task, retry_on_error=3)[0]
    assert log.status == "error"
    assert log.samples is not None
    assert len(log.samples[0].error_retries) == 3
    assert log.samples[0].error is not None


@skip_if_github_action
def test_retry_on_error_concurrency():
    dataset = example_dataset("theory_of_mind")
    solver_failures = [True, False] * len(dataset) * 5
    random.shuffle(solver_failures)
    task = Task(dataset=dataset, solver=failing_solver_deterministic(solver_failures))
    log = eval(task, max_samples=5, retry_on_error=10, fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples
    retries = 0
    for sample in log.samples:
        sample_retries = len(sample.error_retries)
        retries += sample_retries

    # retries should be around 100 but randomness will cause some divergence
    assert retries > 50 and retries < 150


def test_retry_on_error_preserves_sample_uuid():
    task = Task(solver=failing_solver_deterministic([True, True, False]))
    log = eval(task, retry_on_error=3)[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert len(sample.error_retries) == 2
    # UUID should be a non-empty string (basic sanity)
    assert sample.uuid and len(sample.uuid) > 0


def test_retry_on_error_with_epochs():
    # Provide enough fail/succeed pairs for 1 sample * 2 epochs with retries.
    # Retries release the semaphore and go to the back of the queue, so the
    # iterator consumption order is not deterministic. We provide extra entries
    # to handle any ordering and assert on aggregate behavior.
    task = Task(
        solver=failing_solver_deterministic(
            [True, False, True, False, True, False, True, False]
        )
    )
    log = eval(task, retry_on_error=3, epochs=2)[0]
    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 2  # 1 sample * 2 epochs
    # Total retries across both epochs should be at least 1
    total_retries = sum(len(s.error_retries) for s in log.samples)
    assert total_retries >= 1
    # Each sample should have a non-empty UUID
    for sample in log.samples:
        assert sample.uuid and len(sample.uuid) > 0
    # Different epochs must have different UUIDs
    assert log.samples[0].uuid != log.samples[1].uuid


@solver
def _failing_after_generate_solver(should_fail: Sequence[bool]):
    """Solver that calls generate then conditionally fails."""
    it = iter(should_fail)

    async def solve(state: TaskState, generate: Generate):
        state = await generate(state)
        transcript().info("about to check for failure")
        if next(it):
            raise ValueError("Eval failed after generate!")
        return state

    return solve


def _check_retry_events(sample):
    """Verify retry error events have expected content."""
    assert len(sample.error_retries) == 1
    retry_error = sample.error_retries[0]

    # error fields should be populated
    assert "Eval failed after generate!" in retry_error.message
    assert retry_error.traceback != ""
    assert retry_error.traceback_ansi != ""

    # events should be present
    assert retry_error.events is not None
    assert len(retry_error.events) >= 2

    # first event should be a ModelEvent with actual content
    model_event = retry_error.events[0]
    assert model_event.event == "model"
    assert len(model_event.input) > 0
    assert model_event.output is not None
    assert model_event.output.choices is not None

    # should include the InfoEvent with the data we logged
    info_events = [e for e in retry_error.events if e.event == "info"]
    assert len(info_events) == 1
    assert info_events[0].data == "about to check for failure"

    # should also include other intervening events (span_end, logger, etc.)
    assert len(retry_error.events) > 2


def test_retry_on_error_events():
    task = Task(solver=_failing_after_generate_solver([True, False]))
    log = eval(task, model="mockllm/model", retry_on_error=1)[0]
    assert log.status == "success"
    assert log.samples is not None
    _check_retry_events(log.samples[0])


def test_retry_on_error_events_persisted():
    """Verify retry error events survive log serialization and readback."""
    task = Task(solver=_failing_after_generate_solver([True, False]))
    log = eval(task, model="mockllm/model", retry_on_error=1)[0]
    assert log.status == "success"

    # read the log back from disk
    persisted_log = read_eval_log(log.location)
    assert persisted_log.samples is not None
    _check_retry_events(persisted_log.samples[0])
