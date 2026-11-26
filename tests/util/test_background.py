# test that service errors are caught, logged, and re-raised

import functools
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Coroutine, Iterator, NamedTuple

import anyio
import pytest
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai import Task, eval
from inspect_ai.log import EvalLog
from inspect_ai.solver import Solver, solver
from inspect_ai.util import LimitExceededError, background
from inspect_ai.util._background import (
    BackgroundTarget,
    PosArgsT,
    background_target,
)

WORKER_ERROR = "Error in worker!"


class _ScenarioResult(NamedTuple):
    log: EvalLog
    worker_completed: bool


def _run_scenario(*, worker_raises: bool, foreground_raises: bool) -> _ScenarioResult:
    """Run one sample with a background worker and a foreground solver.

    Synchronization is event-driven rather than timing-based so the outcome is
    deterministic under load (e.g. `pytest -n auto`):

    - `worker_ready` guarantees the worker has entered its `try` block before
      the foreground acts, so cancellation cleanup (the `finally`) is always
      exercised.
    - When the worker is expected to raise, the foreground blocks forever, so
      the sample can only end via the worker's error — never by the foreground
      completing first and cancelling the worker before it raises.
    """
    worker_ready = anyio.Event()
    worker_completed = False

    async def worker() -> None:
        nonlocal worker_completed
        try:
            worker_ready.set()
            if worker_raises:
                raise RuntimeError(WORKER_ERROR)
            await anyio.sleep_forever()  # run until the sample cancels us
        finally:
            worker_completed = True

    @solver
    def start_worker() -> Solver:
        async def solve(state, generate):
            background(worker)
            return state

        return solve

    @solver
    def foreground() -> Solver:
        async def solve(state, generate):
            await worker_ready.wait()
            if foreground_raises:
                raise Exception("Error in solver!")
            if worker_raises:
                await anyio.sleep_forever()  # let the worker's error tear us down
            return state

        return solve

    log = eval(Task(solver=[start_worker(), foreground()]))[0]
    return _ScenarioResult(log=log, worker_completed=worker_completed)


def test_background_termination():
    # foreground errors -> background worker is cancelled and cleaned up
    assert _run_scenario(worker_raises=False, foreground_raises=True).worker_completed

    # foreground completes normally -> worker cancelled and cleaned up
    assert _run_scenario(worker_raises=False, foreground_raises=False).worker_completed

    # error in the worker -> propagates and fails the sample
    log = _run_scenario(worker_raises=True, foreground_raises=False).log
    assert log.status == "error"
    assert log.error
    assert WORKER_ERROR in log.error.traceback


class _TaskGroupTarget:
    """A background target over an anyio task group."""

    def __init__(self, tg: TaskGroup) -> None:
        self._tg = tg
        self.started = 0

    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, Any]],
        *args: Unpack[PosArgsT],
    ) -> None:
        self.started += 1
        self._tg.start_soon(func, *args)


class _RecordingTarget:
    """A background target that keeps what it is given, to run by hand."""

    def __init__(self) -> None:
        self.started: list[Callable[[], Awaitable[Any]]] = []

    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, Any]],
        *args: Unpack[PosArgsT],
    ) -> None:
        self.started.append(functools.partial(func, *args))


@contextmanager
def _target(target: BackgroundTarget) -> Iterator[None]:
    token = background_target.set(target)
    try:
        yield
    finally:
        background_target.reset(token)


@contextmanager
def _capture_background_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    # eval() turns off propagation for inspect_ai's loggers, so attach the
    # capture handler to the module's logger directly.
    background_logger = logging.getLogger("inspect_ai.util._background")
    background_logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        background_logger.removeHandler(caplog.handler)


async def _noop() -> None:
    pass


def test_background_outside_sample_raises() -> None:
    with pytest.raises(RuntimeError, match="must be called from a running sample"):
        background(_noop)


async def test_background_target_starts_work_with_caller_context() -> None:
    probe: ContextVar[str] = ContextVar("probe", default="unset")
    seen: list[tuple[int, str]] = []

    async def work(value: int) -> None:
        seen.append((value, probe.get()))

    async with anyio.create_task_group() as tg:
        target = _TaskGroupTarget(tg)
        probe_token = probe.set("caller")
        try:
            with _target(target):
                background(work, 1)
        finally:
            probe.reset(probe_token)

    assert target.started == 1
    assert seen == [(1, "caller")]


async def test_background_target_logs_and_reraises_worker_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def work() -> None:
        raise RuntimeError(WORKER_ERROR)

    target = _RecordingTarget()
    with _target(target):
        background(work)
    assert len(target.started) == 1

    with _capture_background_logs(caplog), pytest.raises(RuntimeError):
        await target.started[0]()
    assert f"Background worker error: {WORKER_ERROR}" in caplog.messages


async def test_background_target_reraises_limit_error_without_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def work() -> None:
        raise LimitExceededError("token", value=2, limit=1)

    target = _RecordingTarget()
    with _target(target):
        background(work)

    with _capture_background_logs(caplog), pytest.raises(LimitExceededError):
        await target.started[0]()
    assert not any("Background worker error" in m for m in caplog.messages)


def test_background_target_reset_restores_sample_path() -> None:
    target = _RecordingTarget()
    with _target(target):
        background(_noop)
    assert len(target.started) == 1

    with pytest.raises(RuntimeError, match="must be called from a running sample"):
        background(_noop)
    assert len(target.started) == 1
