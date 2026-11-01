"""Tests for the sandbox setup of tasks added while a run is in progress.

An added task's sandboxes are set up while other tasks run: the setup must not
be visible to them, a failed setup ends only that task (with an error log,
hooks, a ``TaskSource`` notification and its retries), setup output is
collected (and shown if the setup fails).
"""

import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Literal, overload

import anyio
import pytest
from typing_extensions import override

from inspect_ai import Task, TaskSource, enqueue_task, eval_async
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
from inspect_ai._eval.task.enqueue import TaskOutcome, get_run_queue
from inspect_ai._util.registry import _registry, registry_lookup
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunEnd, TaskEnd, TaskStart, hooks
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


@sandboxenv(name="added_setup_box")
class _AddedSetupBox(SandboxEnvironment):
    @override
    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        return {"ADDED_SETUP_BOX_VAR": "set-for-setup"}

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
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        _box.setdefault("cleanups", []).append(cls.__name__)

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return {"default": _AddedSetupBox()}

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
        name=name, dataset=[Sample(input="x")], solver=noop(), sandbox="added_setup_box"
    )
    if task_dir is not None:
        setattr(task, TASK_RUN_DIR_ATTR, str(task_dir))
    return task


def _plain(name: str, *solvers: Solver) -> Task:
    return Task(name=name, dataset=[Sample(input="x")], solver=list(solvers) or noop())


def _statuses(logs: list[EvalLog]) -> list[tuple[str, str]]:
    return [(log.eval.task, log.status) for log in logs]


async def _wait_ended(*names: str) -> None:
    """Wait until an attempt of each named task has finished (its eval state)."""
    with anyio.fail_after(10):
        while not all(
            any(
                s.task == name and s.completed_at is not None for s in get_eval_states()
            )
            for name in names
        ):
            await anyio.sleep(0.01)


@solver
def add_and_wait(*tasks: Task) -> Solver:
    """Add tasks to the run and wait for them to end."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(list(tasks), start="when_free")
        await _wait_ended(*(task.name for task in tasks))
        return state

    return solve


def _parent(*children: Task, solver: Solver | None = None) -> Task:
    """A parent task that adds `children` while it runs and waits for them."""
    return _plain("parent", *([solver] if solver else []), add_and_wait(*children))


async def test_setup_overlaps_running_sample_without_changing_its_process(
    tmp_path: Path,
) -> None:
    # b's sandbox setup runs while the parent's sample runs; the parent's
    # sample sees neither b's task directory as its working directory nor b's
    # setup env vars
    task_dir = tmp_path / "b_dir"
    task_dir.mkdir()
    init_running = anyio.Event()
    observed = anyio.Event()
    seen: dict[str, Any] = {}

    async def init() -> None:
        init_running.set()
        with anyio.fail_after(10):
            await observed.wait()
        child = await subprocess(["sh", "-c", "pwd; echo $ADDED_SETUP_BOX_VAR"])
        seen["child"] = child.stdout.split()

    @solver
    def add_and_observe() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_boxed("b", task_dir), start="when_free")
            with anyio.fail_after(10):
                await init_running.wait()
            seen["cwd"] = os.getcwd()
            seen["var"] = os.environ.get("ADDED_SETUP_BOX_VAR")
            observed.set()
            await _wait_ended("b")
            return state

        return solve

    _box["task_init"] = init
    launch_dir = os.getcwd()
    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", add_and_observe()), model="mockllm/model", max_tasks=2
        )
    assert _statuses(logs) == [("parent", "success"), ("b", "success")]
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
            _parent(_plain("a"), _boxed("b"), _plain("c")),
            model="mockllm/model",
            max_tasks=2,
        )
    assert sorted(_statuses(logs)) == [
        ("a", "success"),
        ("b", "error"),
        ("c", "success"),
        ("parent", "success"),
    ]
    error = next(log for log in logs if log.eval.task == "b").error
    assert error is not None
    assert "sandbox startup failed" in error.message
    assert "Output of the sandbox setup" in error.traceback
    assert "pulling image layer" in error.traceback


async def test_seed_setup_output_is_streamed_and_its_failure_fails_the_run(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # unlike an added task's, the seed's setup runs before the task display
    # opens: its output goes to the terminal, and a failure ends the run
    async def fail() -> None:
        await subprocess(["sh", "-c", "echo pulling seed image"], capture_output=False)
        raise RuntimeError("seed setup failed")

    _box["task_init"] = fail
    with pytest.raises(RuntimeError, match="seed setup failed"):
        await eval_async([_plain("a"), _boxed("b")], model="mockllm/model")
    assert "pulling seed image" in capfd.readouterr().out


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
            _parent(_boxed("b")),
            model="mockllm/model",
            max_tasks=2,
            task_retry_attempts=1,
        )
    assert _statuses(logs) == [("parent", "success"), ("b", "success")]
    assert calls == 2


async def test_setup_output_is_not_shown_when_setup_succeeds(
    capfd: pytest.CaptureFixture[str],
) -> None:
    async def build() -> None:
        await subprocess(["sh", "-c", "echo building image"], capture_output=False)

    _box["task_init"] = build
    logs = await eval_async(_parent(_boxed("b")), model="mockllm/model", max_tasks=2)
    assert _statuses(logs) == [("parent", "success"), ("b", "success")]
    assert "building image" not in capfd.readouterr().out


@pytest.mark.parametrize("sandboxed", [True, False])
async def test_added_task_with_dataset_paged_to_disk_sets_up(sandboxed: bool) -> None:
    task = _boxed("b") if sandboxed else _plain("b")
    logs = await eval_async(
        _parent(task), model="mockllm/model", max_tasks=2, max_dataset_memory=0
    )
    assert _statuses(logs) == [("parent", "success"), ("b", "success")]
    assert _box.get("inits", []) == (["startup"] if sandboxed else [])


async def test_setup_output_is_kept_when_a_call_times_out() -> None:
    # output is collected as it arrives, in the order written, so a call cut
    # short still shows what it wrote
    async def stall() -> None:
        await subprocess(
            ["sh", "-c", "echo out-1; echo err-1 >&2; echo out-2; exec sleep 30"],
            capture_output=False,
            timeout=1,
        )

    _box["task_init"] = stall
    logs = await eval_async(_parent(_boxed("b")), model="mockllm/model", max_tasks=2)
    assert _statuses(logs) == [("parent", "success"), ("b", "error")]
    error = logs[1].error
    assert error is not None
    shown = error.traceback.split("Output of the sandbox setup:")[1]
    assert shown.split() == ["out-1", "err-1", "out-2"]


async def test_collected_setup_output_keeps_multibyte_characters() -> None:
    # output arrives in chunks that may split a multibyte character
    async def emit() -> None:
        await subprocess(
            ["python3", "-c", "import sys; sys.stdout.write('é' * 5000); sys.exit(1)"],
            capture_output=False,
        )
        raise RuntimeError("setup failed")

    _box["task_init"] = emit
    logs = await eval_async(_parent(_boxed("b")), model="mockllm/model", max_tasks=2)
    error = logs[1].error
    assert error is not None and "�" not in error.traceback
    assert "éééé" in error.traceback


# --- a task's lifecycle: hooks, control channel and logs agree --------------------


class _Lifecycle(Hooks):
    """Records the task hooks, and the control channel's eval states at run end."""

    def __init__(self) -> None:
        self.starts: list[tuple[str, str]] = []
        self.ends: list[tuple[str, str]] = []
        self.states: dict[str, tuple[str, bool]] | None = None

    async def on_task_start(self, data: TaskStart) -> None:
        self.starts.append((data.spec.task, data.eval_id))

    async def on_task_end(self, data: TaskEnd) -> None:
        self.ends.append((data.log.eval.task, data.eval_id))

    async def on_run_end(self, data: RunEnd) -> None:
        self.states = {
            state.eval_id: (state.task, state.completed_at is not None)
            for state in get_eval_states()
        }


@pytest.fixture
def lifecycle() -> Iterator[_Lifecycle]:
    @hooks("added_setup_lifecycle", description="Records task lifecycle events")
    def get_hooks() -> type[_Lifecycle]:
        return _Lifecycle

    hook = registry_lookup("hooks", "added_setup_lifecycle")
    assert isinstance(hook, _Lifecycle)
    try:
        yield hook
    finally:
        del _registry["hooks:added_setup_lifecycle"]


async def _checked_attempts(
    lifecycle: _Lifecycle, log_dir: Path
) -> list[tuple[str, str]]:
    """Check that hooks, eval states and logs agree on every attempt; return them.

    Every attempt that started has one ``on_task_start``, one ``on_task_end``,
    one control-channel eval state, finished (``completed_at``) by the end of
    the run, and one log on disk. Returns (task, status) per attempt, sorted.
    """
    on_disk = {
        header.eval.eval_id: (header.eval.task, header.status)
        for header in [
            await read_eval_log_async(info, header_only=True)
            for info in list_eval_logs(str(log_dir))
        ]
    }
    starts = {eval_id: task for task, eval_id in lifecycle.starts}
    assert len(starts) == len(lifecycle.starts), lifecycle.starts
    assert lifecycle.states is not None
    assert set(on_disk) == set(starts) == set(lifecycle.states), (
        on_disk,
        lifecycle.starts,
        lifecycle.states,
    )
    assert all(done for _, done in lifecycle.states.values()), lifecycle.states
    assert sorted(lifecycle.ends) == sorted(lifecycle.starts)
    return sorted(on_disk.values())


@solver
def add_child_and_watch(child: Task, seen: dict[str, Any]) -> Solver:
    """Add `child` and watch for it as other tasks can: hooks and eval state."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(child, start="when_free")
        await _wait_ended("child")
        seen["child_ended_while_parent_ran"] = True
        return state

    return solve


async def test_failed_setup_ends_a_task_others_can_see(
    tmp_path: Path, lifecycle: _Lifecycle
) -> None:
    # a parent adds a child whose setup fails: the child starts (hooks,
    # control channel) and ends with an error log, and the parent sees it
    # end while the parent runs
    async def fail() -> None:
        raise RuntimeError("image pull failed")

    _box["task_init"] = fail
    seen: dict[str, Any] = {}
    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", add_child_and_watch(_boxed("child"), seen)),
            model="mockllm/model",
            max_tasks=2,
        )
    assert _statuses(logs) == [("parent", "success"), ("child", "error")]
    assert seen == {"child_ended_while_parent_ran": True}
    assert await _checked_attempts(lifecycle, tmp_path / "logs") == [
        ("child", "error"),
        ("parent", "success"),
    ]


async def _fail_once() -> None:
    _box["calls"] = _box.get("calls", 0) + 1
    if _box["calls"] == 1:
        raise RuntimeError("transient registry error")


async def _succeed() -> None:
    pass


@pytest.mark.parametrize(
    "task_init,retries,expected",
    [
        (_succeed, 0, [("child", "success")]),
        (_fail_once, 1, [("child", "error"), ("child", "success")]),
    ],
    ids=["success", "fail_then_retry"],
)
async def test_lifecycle_of_a_task_by_how_its_setup_ends(
    tmp_path: Path,
    lifecycle: _Lifecycle,
    task_init: Callable[[], Awaitable[None]],
    retries: int,
    expected: list[tuple[str, str]],
) -> None:
    # however a setup ends, the task has the hooks, control-channel states and
    # logs of any started task; a failed setup's retry sets up again
    _box["task_init"] = task_init
    with anyio.fail_after(30):
        await eval_async(
            _plain("parent", add_child_and_watch(_boxed("child"), {})),
            model="mockllm/model",
            max_tasks=2,
            task_retry_attempts=retries,
        )
    attempts = await _checked_attempts(lifecycle, tmp_path / "logs")
    assert attempts == sorted(expected + [("parent", "success")])


async def test_task_source_hears_a_task_whose_setup_failed() -> None:
    completed: list[tuple[str, str]] = []

    async def fail() -> None:
        raise RuntimeError("image pull failed")

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_plain("parent")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            completed.append((log.eval.task, log.status))
            return [_boxed("child")] if log.eval.task == "parent" else None

    _box["task_init"] = fail
    with anyio.fail_after(30):
        logs = await eval_async(Source(), model="mockllm/model")
    assert completed == [("parent", "success"), ("child", "error")]
    assert _statuses(logs) == completed


@pytest.mark.parametrize("how", ["cancel", "drain"])
async def test_operator_cancel_of_a_task_waiting_for_its_setup(
    tmp_path: Path, lifecycle: _Lifecycle, how: str
) -> None:
    # a task cancelled or drained by id while its setup runs ends without
    # starting: no log, no hooks, no retry. A repeat is a no-op, a resolution
    # is rejected, and the setup runs on and is cleaned up at the end of the
    # run
    from inspect_ai._control.cancel import cancel_task, drain_task

    in_setup = anyio.Event()
    release = anyio.Event()
    outcomes: list[Any] = []

    async def init() -> None:
        in_setup.set()
        with anyio.fail_after(10):
            await release.wait()

    @solver
    def add_and_cancel() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_boxed("child"), start="when_free")
            queue = get_run_queue()
            assert queue is not None
            [child] = queue.unstarted()
            with anyio.fail_after(10):
                await in_setup.wait()
            assert cancel_task(child.task_id, action="score") == {
                "ok": False,
                "error": (
                    f"task {child.task_id} has not started, so there are no "
                    "samples for a resolution to apply to; use a plain cancel "
                    "(or drain) to end it without running"
                ),
            }
            result = (cancel_task if how == "cancel" else drain_task)(child.task_id)
            assert result is not None and result.get("not_started")
            with anyio.fail_after(10):
                while child.outcome is None:
                    await anyio.sleep(0.01)
            outcomes.append(child.outcome)
            again = cancel_task(child.task_id)
            assert again is not None and again.get("changed") is False
            assert cancel_task("no-such-task") is None
            release.set()
            return state

        return solve

    _box["task_init"] = init
    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", add_and_cancel()),
            model="mockllm/model",
            max_tasks=2,
            task_retry_attempts=2,
        )
    assert _statuses(logs) == [("parent", "success")]
    assert outcomes == [TaskOutcome(None)]
    assert await _checked_attempts(lifecycle, tmp_path / "logs") == [
        ("parent", "success")
    ]
    assert _box["inits"] == ["startup"]
    assert _box["cleanups"] == ["_AddedSetupBox"]


async def test_operator_cancel_of_a_task_as_it_starts(
    tmp_path: Path, lifecycle: _Lifecycle, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a cancel by id that lands after the loop started the task's attempt but
    # before it registered: the attempt bails, and the task ends with no log
    from inspect_ai._control.cancel import cancel_task
    from inspect_ai._eval import run as run_module

    seen: dict[str, Any] = {}
    open_log = run_module.open_log

    async def open_log_then_cancel(logger: Any, *, retry: bool) -> None:
        await open_log(logger, retry=retry)
        if logger.eval.task == "child":
            seen["result"] = cancel_task(logger.eval.task_id)

    monkeypatch.setattr(run_module, "open_log", open_log_then_cancel)

    @solver
    def add_and_wait_for_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_plain("child"), start="when_free")
            queue = get_run_queue()
            assert queue is not None
            [child] = queue.unstarted()
            with anyio.fail_after(10):
                while child.outcome is None:
                    await anyio.sleep(0.01)
            seen["outcome"] = child.outcome
            return state

        return solve

    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", add_and_wait_for_child()),
            model="mockllm/model",
            max_tasks=2,
        )
    assert seen["result"].get("not_started")
    assert _statuses(logs) == [("parent", "success")]
    assert seen["outcome"] == TaskOutcome(None)
    assert await _checked_attempts(lifecycle, tmp_path / "logs") == [
        ("parent", "success")
    ]


async def test_run_cancel_during_setup_beside_a_running_task(
    tmp_path: Path, lifecycle: _Lifecycle
) -> None:
    # the run is cancelled while the child sets up and the parent runs: the
    # cancellation propagates (the child has no log), and the parent ends
    # cancelled
    entered = anyio.Event()

    async def block() -> None:
        entered.set()
        await anyio.sleep_forever()

    @solver
    def add_child_and_wait() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_boxed("child"), start="when_free")
            await anyio.sleep_forever()
            return state

        return solve

    _box["task_init"] = block
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_entered() -> None:
                    await entered.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_entered)
                await eval_async(
                    _plain("parent", add_child_and_wait()),
                    model="mockllm/model",
                    max_tasks=2,
                )
                pytest.fail("eval_async returned from a cancelled run")
    assert scope.cancelled_caught
    assert await _checked_attempts(lifecycle, tmp_path / "logs") == [
        ("parent", "cancelled")
    ]


@sandboxenv(name="added_setup_box_2")
class _AddedSetupBox2(_AddedSetupBox):
    """A second sandbox type, whose setup fails while ``_box["fail_2"]`` is set."""

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        _box.setdefault("inits", []).append("box2")
        if _box.get("fail_2"):
            _box["fail_2"] -= 1
            raise RuntimeError("box2 setup failed")


def _two_box_task(name: str) -> Task:
    return Task(
        name=name,
        dataset=[
            Sample(input="x", id=1, sandbox="added_setup_box"),
            Sample(input="x", id=2, sandbox="added_setup_box_2"),
        ],
        solver=noop(),
    )


async def test_partly_failed_setup_keeps_the_config_that_succeeded() -> None:
    # t uses two configs: the first sets up, the second fails. The first is
    # set up for good (cleaned up once, at the end), so u (on the first)
    # starts without setting it up again, and t's retry sets up only the
    # second
    _box["fail_2"] = 1
    with anyio.fail_after(30):
        logs = await eval_async(
            _parent(_two_box_task("t"), _boxed("u")),
            model="mockllm/model",
            max_tasks=3,
            task_retry_attempts=1,
        )
    assert sorted(_statuses(logs)) == [
        ("parent", "success"),
        ("t", "success"),
        ("u", "success"),
    ]
    assert sorted(_box["inits"]) == ["box2", "box2", "startup"]
    assert sorted(_box["cleanups"]) == ["_AddedSetupBox", "_AddedSetupBox2"]


@pytest.mark.parametrize("added", [False, True])
async def test_task_init_that_finishes_during_a_run_cancel_is_cleaned_up(
    added: bool,
) -> None:
    # a provider shields its task_init's resource creation; the run is
    # cancelled while it runs. task_init returns normally, so its
    # task_cleanup runs at the end of the run
    entered = anyio.Event()

    async def shielded() -> None:
        with anyio.CancelScope(shield=True):
            entered.set()
            await anyio.sleep(0.2)
        _box["init_done"] = True

    @solver
    def add_and_block() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_boxed("child"), start="when_free")
            await anyio.sleep_forever()
            return state

        return solve

    _box["task_init"] = shielded
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_entered() -> None:
                    await entered.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_entered)
                await eval_async(
                    _plain("parent", add_and_block()) if added else _boxed("a"),
                    model="mockllm/model",
                    max_tasks=2,
                )
    assert _box.get("init_done") is True
    assert _box["cleanups"] == ["_AddedSetupBox"]


async def test_added_task_whose_log_cannot_be_created_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # an added task's logger is created when it starts; as for a log that
    # cannot be created at the start of the run, that fails the run
    from inspect_ai._eval.task.log import TaskLogger

    init = TaskLogger.init

    async def failing_init(logger: TaskLogger) -> None:
        if logger.eval.task == "child":
            raise OSError("log directory unreachable")
        await init(logger)

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    with (
        anyio.fail_after(30),
        pytest.raises(OSError, match="log directory unreachable"),
    ):
        await eval_async(_parent(_plain("child")), model="mockllm/model", max_tasks=2)
