"""Tests for tasks starting their sandboxes in their own slots.

With ``INSPECT_TASK_SETUP_IN_SLOT=1`` each task starts its sandboxes when it
starts running (in ``task_run``, before its samples), while other tasks run:
the setup must not be visible to them, a failed setup fails only its task,
setup output is collected for the task, and ``ctl`` sandbox limits are
registered when a task is queued.
"""

import os
from pathlib import Path
from typing import Any, Literal, overload

import anyio
import pytest
from typing_extensions import override

from inspect_ai import Task, enqueue_task, eval_async
from inspect_ai._control.max_tasks import task_dispatcher_stats
from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log_async
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandboxenv,
    subprocess,
)
from inspect_ai.util._display import init_display_type

# what the box's task_init does, set per test
_box: dict[str, Any] = {}


@sandboxenv(name="slot_box")
class _SlotBox(SandboxEnvironment):
    @override
    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        return {"SLOT_BOX_VAR": "set-for-setup"}

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        _box.setdefault("inits", []).append(task_name)
        hook = _box.get("task_init")
        if hook is not None:
            await hook()

    @override
    @classmethod
    def default_concurrency(cls) -> int | None:
        return 10

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return {"default": _SlotBox()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass

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


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setenv("INSPECT_TASK_SETUP_IN_SLOT", "1")
    monkeypatch.setenv("INSPECT_LOG_DIR", str(tmp_path / "logs"))
    init_display_type("none")
    _box.clear()
    yield
    _box.clear()


@solver
def noop() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def _boxed(name: str, task_dir: Path | None = None) -> Task:
    task = Task(
        name=name, dataset=[Sample(input="x")], solver=noop(), sandbox="slot_box"
    )
    if task_dir is not None:
        setattr(task, TASK_RUN_DIR_ATTR, str(task_dir))
    return task


def _plain(name: str, *solvers: Solver) -> Task:
    return Task(name=name, dataset=[Sample(input="x")], solver=list(solvers) or noop())


def _statuses(logs: list[EvalLog]) -> list[tuple[str, str]]:
    return [(log.eval.task, log.status) for log in logs]


async def test_setup_overlaps_running_sample_without_changing_its_process(
    tmp_path: Path,
) -> None:
    # b's sandbox setup runs while a's sample runs; a's sample sees neither
    # b's task directory as its working directory nor b's setup env vars
    task_dir = tmp_path / "b_dir"
    task_dir.mkdir()
    init_running = anyio.Event()
    observed = anyio.Event()
    seen: dict[str, Any] = {}

    async def init() -> None:
        init_running.set()
        with anyio.fail_after(10):
            await observed.wait()
        child = await subprocess(["sh", "-c", "pwd; echo $SLOT_BOX_VAR"])
        seen["child"] = child.stdout.split()

    @solver
    def observe() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with anyio.fail_after(10):
                await init_running.wait()
            seen["cwd"] = os.getcwd()
            seen["var"] = os.environ.get("SLOT_BOX_VAR")
            observed.set()
            return state

        return solve

    _box["task_init"] = init
    launch_dir = os.getcwd()
    with anyio.fail_after(30):
        logs = await eval_async(
            [_plain("a", observe()), _boxed("b", task_dir)],
            model="mockllm/model",
            max_tasks=2,
        )
    assert _statuses(logs) == [("a", "success"), ("b", "success")]
    assert seen["cwd"] == launch_dir
    assert seen["var"] is None
    # b's own setup child processes ran in b's directory with its env var
    assert seen["child"] == [str(task_dir), "set-for-setup"]


async def test_setup_failure_fails_only_its_task() -> None:
    # a failed setup is its task's error, with the setup's collected output;
    # the run goes on
    async def fail() -> None:
        await subprocess(["sh", "-c", "echo pulling image layer"], capture_output=False)
        raise RuntimeError("sandbox startup failed")

    _box["task_init"] = fail
    with anyio.fail_after(30):
        logs = await eval_async(
            [_plain("a"), _boxed("b"), _plain("c")], model="mockllm/model", max_tasks=1
        )
    assert _statuses(logs) == [("a", "success"), ("b", "error"), ("c", "success")]
    error = logs[1].error
    assert error is not None
    assert "sandbox startup failed" in error.message
    assert "Output of the sandbox setup" in error.traceback
    assert "pulling image layer" in error.traceback


async def test_failed_setup_is_retried() -> None:
    calls = 0

    async def fail_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient registry error")

    _box["task_init"] = fail_once
    with anyio.fail_after(30):
        logs = await eval_async(
            _boxed("b"), model="mockllm/model", task_retry_attempts=1
        )
    assert _statuses(logs) == [("b", "success")]
    assert calls == 2


async def test_setup_output_is_not_shown_when_setup_succeeds(
    capfd: pytest.CaptureFixture[str],
) -> None:
    async def build() -> None:
        await subprocess(["sh", "-c", "echo building image"], capture_output=False)

    _box["task_init"] = build
    logs = await eval_async(_boxed("b"), model="mockllm/model")
    assert _statuses(logs) == [("b", "success")]
    assert "building image" not in capfd.readouterr().out


async def test_max_sandboxes_retune_reaches_task_waiting_to_start() -> None:
    # the sandbox type's ctl limiter is registered when the task is queued, so
    # a retune while it waits behind max_tasks (before its setup) reaches it
    from inspect_ai._control.limits import _apply_process_knobs
    from inspect_ai.util._concurrency import sandbox_limiters

    seen: dict[str, Any] = {}

    @solver
    def record_limit() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen["limit"] = sandbox_limiters()["slot_box"].concurrency
            return state

        return solve

    @solver
    def add_and_retune() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            child = _boxed("b")
            child.solver = record_limit()
            enqueue_task(child, start="when_free")
            with anyio.fail_after(10):
                while (stats := task_dispatcher_stats()) is None or stats.pending != 1:
                    await anyio.sleep(0)
            assert _box.get("inits") is None
            views = _apply_process_knobs(
                max_sandboxes=3,
                max_subprocesses=None,
                max_connections=None,
                model=None,
                dry_run=False,
            )
            seen["warnings"] = list(views.warnings)
            return state

        return solve

    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("a", add_and_retune()), model="mockllm/model", max_tasks=1
        )
    assert _statuses(logs) == [("a", "success"), ("b", "success")]
    assert seen == {"warnings": [], "limit": 3}


async def test_cancel_during_setup_cancels_the_task(tmp_path: Path) -> None:
    # a cancellation of the run while a task sets up in its slot is handled as
    # for any running task: the run returns (the cancellation is absorbed) and
    # the task's log on disk is cancelled
    entered = anyio.Event()

    async def block() -> None:
        entered.set()
        await anyio.sleep_forever()

    _box["task_init"] = block
    returned: list[list[EvalLog]] = []
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_entered() -> None:
                    await entered.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_entered)
                returned.append(await eval_async(_boxed("b"), model="mockllm/model"))
    assert len(returned) == 1 or scope.cancelled_caught
    on_disk = [
        (await read_eval_log_async(info, header_only=True)).status
        for info in list_eval_logs(str(tmp_path / "logs"))
    ]
    assert on_disk == ["cancelled"]
