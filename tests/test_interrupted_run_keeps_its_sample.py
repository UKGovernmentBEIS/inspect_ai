"""Regression coverage for cancellation after scoring and before sample logging."""

import asyncio
import contextlib
from pathlib import Path
from typing import Any, AsyncIterator, Literal, overload

import anyio
import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_trio
from typing_extensions import override

import inspect_ai._display.core.active as active_display_module
import inspect_ai.util._display as display_type_module
from inspect_ai import Task, eval, eval_async
from inspect_ai._display.core.display import TaskScreen, TaskSpec
from inspect_ai._eval.run import _run_task_screen
from inspect_ai._util._async import current_async_backend
from inspect_ai._util.background import background_task_group
from inspect_ai._util.error import is_cancellation_message
from inspect_ai.dataset import Sample
from inspect_ai.event import ErrorEvent
from inspect_ai.log import (
    EvalLog,
    EvalSample,
    list_eval_logs_async,
    read_eval_log_async,
)
from inspect_ai.scorer import CORRECT, Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    sandboxenv,
)


class _InterruptStageConfig(BaseModel, frozen=True):
    """Select when the fake sandbox interrupts the current evaluation."""

    stage: Literal["scoring", "cleanup", "partial_cleanup", "hanging_cleanup"]


@sandboxenv(name="interrupt_after_scoring")
class _InterruptAfterScoringSandbox(SandboxEnvironment):
    """Fake sandbox that can cancel the real evaluation during cleanup."""

    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return _InterruptStageConfig.model_validate(config)

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return {"default": _InterruptAfterScoringSandbox()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        assert isinstance(config, _InterruptStageConfig)
        if config.stage in ("cleanup", "partial_cleanup", "hanging_cleanup"):
            _cancel_evaluation()
            await anyio.sleep(0)
        if config.stage == "hanging_cleanup":
            await anyio.sleep_forever()

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        raise NotImplementedError

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise NotImplementedError

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError


def _cancel_evaluation() -> None:
    task_group = background_task_group()
    assert task_group is not None
    task_group.cancel_scope.cancel()


@solver(name="interrupt_after_scoring_solver")
def _interrupt_after_scoring_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def _interrupt_after_scoring_scorer(
    stage: Literal["scoring", "cleanup", "partial_cleanup", "hanging_cleanup"],
) -> Scorer:
    @scorer(metrics=[], name=f"interrupt_after_scoring_{stage}_scorer")
    def score() -> Scorer:
        async def score_sample(state: TaskState, target: Target) -> Score:
            if stage == "scoring":
                raise asyncio.CancelledError()
            return Score(value=CORRECT)

        return score_sample

    return score()


def _partial_scoring_scorers() -> list[Scorer]:
    @scorer(metrics=[], name="partial_scoring_first")
    def first() -> Scorer:
        async def score_sample(state: TaskState, target: Target) -> Score:
            return Score(value=CORRECT)

        return score_sample

    @scorer(metrics=[], name="partial_scoring_second")
    def second() -> Scorer:
        async def score_sample(state: TaskState, target: Target) -> Score:
            raise RuntimeError("second scorer failed")

        return score_sample

    return [first(), second()]


async def _interrupted_eval(
    stage: Literal["scoring", "cleanup", "partial_cleanup", "hanging_cleanup"],
    tmp_path: Path,
    scorer_override: Scorer | list[Scorer] | None = None,
) -> EvalLog:
    eval_scorer = (
        _interrupt_after_scoring_scorer(stage)
        if scorer_override is None
        else scorer_override
    )
    returned = await eval_async(
        Task(
            dataset=[Sample(id="scored", input="x", target="y")],
            solver=[_interrupt_after_scoring_solver()],
            scorer=eval_scorer,
            sandbox=SandboxEnvironmentSpec(
                "interrupt_after_scoring", _InterruptStageConfig(stage=stage)
            ),
            name=f"interrupt_after_scoring_{stage}",
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        ctl_server=False,
        fail_on_error=False,
    )
    logs = await list_eval_logs_async(str(tmp_path))
    assert len(logs) == 1
    log = await read_eval_log_async(logs[0].name)
    if log.status == "cancelled" and current_async_backend() == "asyncio":
        # asyncio returns no logs for a run whose task group is cancelled
        assert returned == []
    else:
        assert [r.eval.eval_id for r in returned] == [log.eval.eval_id]
        assert returned[0].status == log.status
    return log


def _logged_sample(log: EvalLog) -> EvalSample:
    assert log.samples is not None and len(log.samples) == 1
    return log.samples[0]


async def test_interrupted_sandbox_cleanup_keeps_scored_sample(tmp_path: Path) -> None:
    """A cancel in teardown keeps the score-bearing sample in the cancelled log."""
    log = await _interrupted_eval("cleanup", tmp_path)

    assert log.status == "cancelled"
    sample = _logged_sample(log)
    assert sample.scores
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)


@pytest.fixture
def sync_rich_eval_first(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run a sync `eval()` with the rich display before the test's event loop.

    The sync run leaves its display in place for later runs in the process,
    so the test's `eval_async()` uses the rich display. The display created
    by earlier tests is cleared first and the display state is restored
    afterwards.
    """
    monkeypatch.setattr(
        display_type_module, "_display_type", display_type_module._display_type
    )
    monkeypatch.setattr(active_display_module, "_active_display", None)
    eval(
        Task(dataset=[Sample(input="x", target="y")]),
        model="mockllm/model",
        log_dir=str(tmp_path_factory.mktemp("sync_eval")),
        display="rich",
    )


@pytest.mark.usefixtures("sync_rich_eval_first")
async def test_interrupted_cleanup_after_sync_eval_keeps_scored_sample(
    tmp_path: Path,
) -> None:
    """A teardown cancel keeps the cancelled log when the rich display is active."""
    log = await _interrupted_eval("cleanup", tmp_path)

    assert log.status == "cancelled"
    sample = _logged_sample(log)
    assert sample.scores
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)


class _CheckpointTeardownDisplay:
    """Display whose task screen teardown awaits, optionally cancelling first."""

    def __init__(self, cancel_in_teardown: anyio.CancelScope | None = None) -> None:
        self.cancel_in_teardown = cancel_in_teardown

    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        yield TaskScreen()
        if self.cancel_in_teardown is not None:
            self.cancel_in_teardown.cancel()
        await anyio.sleep(0)


async def test_run_task_screen_absorbs_teardown_cancel_after_body_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled run body returns, though the display's teardown re-raises the cancel."""
    monkeypatch.setattr(
        "inspect_ai._eval.run.display", lambda: _CheckpointTeardownDisplay()
    )
    returned = False
    with anyio.CancelScope() as scope:
        async with _run_task_screen([]):
            scope.cancel()
            await anyio.sleep(0)
        returned = True
    assert returned


async def test_run_task_screen_propagates_teardown_cancel_after_normal_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancel that first arrives in the display's teardown still propagates."""
    with anyio.CancelScope() as scope:
        monkeypatch.setattr(
            "inspect_ai._eval.run.display",
            lambda: _CheckpointTeardownDisplay(cancel_in_teardown=scope),
        )
        async with _run_task_screen([]):
            pass
        pytest.fail("teardown cancel was absorbed")
    assert scope.cancelled_caught


@pytest.mark.timeout(10, method="thread")
async def test_interrupted_hanging_cleanup_keeps_scored_sample(
    tmp_path: Path,
) -> None:
    """A ten-second timeout catches a shielded cleanup hang far below 300 seconds."""
    log = await _interrupted_eval("hanging_cleanup", tmp_path)

    assert log.status == "cancelled"
    sample = _logged_sample(log)
    assert sample.scores
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)


async def test_interrupted_cleanup_keeps_partial_scoring_sample(
    tmp_path: Path,
) -> None:
    """A teardown cancel preserves partial scores and the scorer-error event."""
    log = await _interrupted_eval(
        "partial_cleanup", tmp_path, _partial_scoring_scorers()
    )

    assert log.status == "cancelled"
    sample = _logged_sample(log)
    assert sample.scores is not None
    assert sample.scores["partial_scoring_first"].value == CORRECT
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)
    assert any(
        isinstance(event, ErrorEvent) and "second scorer failed" in event.error.message
        for event in sample.events
    )


@skip_if_trio
async def test_interrupted_scoring_keeps_cancelled_sample(tmp_path: Path) -> None:
    """Control: cancellation while scoring already keeps the cancelled sample."""
    log = await _interrupted_eval("scoring", tmp_path)

    assert log.status == "success"
    sample = _logged_sample(log)
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)
