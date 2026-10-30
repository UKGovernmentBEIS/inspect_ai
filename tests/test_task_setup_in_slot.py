"""Tests for tasks starting their own sandboxes (slot mode).

With ``INSPECT_TASK_SETUP_IN_SLOT=1`` each task starts its sandboxes once it
has started (in ``task_run``, before its samples), while other tasks run: the
setup must not be visible to them, a failed setup fails only its task, setup
output is collected for the task, and ``ctl`` sandbox limits are registered
when a task is queued. A task with setup to do starts in the dispatcher's
setup lane (one task at a time, outside the ``max_tasks`` slots), and its
lifecycle (hooks, control channel, log) is that of any started task.
"""

import os
from pathlib import Path
from typing import Any, Literal, overload

import anyio
import pytest
from typing_extensions import override

from inspect_ai import SampleSource, Task, enqueue_task, eval_async
from inspect_ai._control.eval_state import EvalState, get_eval_states
from inspect_ai._control.max_tasks import task_dispatcher_stats
from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
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


@sandboxenv(name="slot_box_2")
class _SlotBox2(_SlotBox):
    """A second sandbox type, for tests that need two."""


async def test_max_sandboxes_retune_reaches_task_waiting_to_start(
    tmp_path: Path,
) -> None:
    # the sandbox type's ctl limiter is registered when the task is queued, so
    # a retune while it waits for the setup lane (behind another task's
    # setup) reaches it
    from inspect_ai._control.limits import _apply_process_knobs
    from inspect_ai.util import sandbox_setup
    from inspect_ai.util._concurrency import sandbox_limiters

    first_dir, child_dir = tmp_path / "first", tmp_path / "child"
    first_dir.mkdir()
    child_dir.mkdir()
    release = anyio.Event()
    first_in_setup = anyio.Event()
    seen: dict[str, Any] = {}

    async def init() -> None:
        setup = sandbox_setup()
        assert setup is not None
        if setup.task_dir == str(first_dir):
            first_in_setup.set()
            with anyio.fail_after(10):
                await release.wait()
        else:
            seen["child_setup_after_release"] = release.is_set()

    @solver
    def record_limit() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen["limit"] = sandbox_limiters()["slot_box_2"].concurrency
            return state

        return solve

    @solver
    def add_and_retune() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            first = _boxed("first", first_dir)
            child = Task(
                name="child",
                dataset=[Sample(input="x")],
                solver=record_limit(),
                sandbox="slot_box_2",
            )
            setattr(child, TASK_RUN_DIR_ATTR, str(child_dir))
            enqueue_task([first, child], start="when_free")
            with anyio.fail_after(10):
                await first_in_setup.wait()
                while "slot_box_2" not in sandbox_limiters():
                    await anyio.sleep(0)
            # this task in its slot, first in the setup lane, child waiting
            stats = task_dispatcher_stats()
            assert stats is not None and (stats.in_flight, stats.pending) == (2, 1)
            views = _apply_process_knobs(
                max_sandboxes=3,
                max_subprocesses=None,
                max_connections=None,
                model=None,
                dry_run=False,
            )
            seen["warnings"] = list(views.warnings)
            release.set()
            return state

        return solve

    _box["task_init"] = init
    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("a", add_and_retune()), model="mockllm/model", max_tasks=1
        )
    assert _statuses(logs) == [
        ("a", "success"),
        ("first", "success"),
        ("child", "success"),
    ]
    assert seen == {"warnings": [], "child_setup_after_release": True, "limit": 3}


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


@pytest.mark.parametrize("sandboxed", [True, False])
async def test_task_with_dataset_paged_to_disk_sets_up(sandboxed: bool) -> None:
    task = _boxed("b") if sandboxed else _plain("b")
    logs = await eval_async(task, model="mockllm/model", max_dataset_memory=0)
    assert _statuses(logs) == [("b", "success")]
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
    logs = await eval_async(_boxed("b"), model="mockllm/model")
    assert _statuses(logs) == [("b", "error")]
    error = logs[0].error
    assert error is not None
    shown = error.traceback.split("Output of the sandbox setup:")[1]
    assert shown.split() == ["out-1", "err-1", "out-2"]


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
def lifecycle() -> Any:
    @hooks("slot_lifecycle", description="Records task lifecycle events")
    def get_hooks() -> type[_Lifecycle]:
        return _Lifecycle

    hook = registry_lookup("hooks", "slot_lifecycle")
    assert isinstance(hook, _Lifecycle)
    try:
        yield hook
    finally:
        del _registry["hooks:slot_lifecycle"]


async def _agreed_attempts(
    lifecycle: _Lifecycle, log_dir: Path
) -> list[tuple[str, str]]:
    """Check that hooks, eval states and logs agree on every attempt; return them.

    Every attempt that started has one ``on_task_start``, one control-channel
    eval state, finished (``completed_at``) by the end of the run, and one log
    on disk. ``on_task_end`` fires for the attempts that completed their
    samples (success logs here), as for any task. Returns (task, status) per
    attempt, sorted.
    """
    on_disk = {
        header.eval.eval_id: (header.eval.task, header.status)
        for header in [
            await read_eval_log_async(info, header_only=True)
            for info in list_eval_logs(str(log_dir))
        ]
    }
    starts = dict((eval_id, task) for task, eval_id in lifecycle.starts)
    assert len(starts) == len(lifecycle.starts), lifecycle.starts
    assert lifecycle.states is not None
    assert set(on_disk) == set(starts) == set(lifecycle.states), (
        on_disk,
        lifecycle.starts,
        lifecycle.states,
    )
    assert all(done for _, done in lifecycle.states.values()), lifecycle.states
    assert sorted(lifecycle.ends) == sorted(
        (task, eval_id)
        for eval_id, (task, status) in on_disk.items()
        if status == "success"
    )
    return sorted(on_disk.values())


def _child_state() -> EvalState:
    (state,) = [s for s in get_eval_states() if s.task == "child"]
    return state


@solver
def add_child_and_watch(child: Task, seen: dict[str, Any]) -> Solver:
    """Add `child` and watch for it as other tasks can: hooks and eval state."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(child, start="when_free")
        with anyio.fail_after(10):
            while not any(
                s.task == "child" and s.completed_at is not None
                for s in get_eval_states()
            ):
                await anyio.sleep(0.01)
        seen["child_ended_while_parent_ran"] = True
        return state

    return solve


async def test_failed_setup_ends_a_task_others_can_see(
    tmp_path: Path, lifecycle: _Lifecycle
) -> None:
    # a parent adds a child whose setup fails: the child has started (hook,
    # control channel), and the parent sees it end while the parent runs
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
    assert await _agreed_attempts(lifecycle, tmp_path / "logs") == [
        ("child", "error"),
        ("parent", "success"),
    ]


async def _abort_child_in_setup() -> None:
    # as `inspect ctl task cancel` does: the started child's cancel handle
    cancel = _child_state().task_cancel
    assert cancel is not None
    cancel.cancel_task("abort")
    await anyio.sleep_forever()


async def _fail_once() -> None:
    _box["calls"] = _box.get("calls", 0) + 1
    if _box["calls"] == 1:
        raise RuntimeError("transient registry error")


@pytest.mark.parametrize(
    "ending,retries,expected",
    [
        ("success", 0, [("child", "success")]),
        ("fail", 0, [("child", "error")]),
        ("fail_once", 1, [("child", "error"), ("child", "success")]),
        ("abort", 1, [("child", "error")]),
    ],
)
async def test_lifecycle_of_a_task_by_how_its_setup_ends(
    tmp_path: Path,
    lifecycle: _Lifecycle,
    ending: str,
    retries: int,
    expected: list[tuple[str, str]],
) -> None:
    # every way a setup ends gives the hooks, control-channel states and logs
    # of any started task; an abort during setup is not retried
    async def fail() -> None:
        raise RuntimeError("setup failed")

    endings = {
        "success": None,
        "fail": fail,
        "fail_once": _fail_once,
        "abort": _abort_child_in_setup,
    }
    _box["task_init"] = endings[ending]
    with anyio.fail_after(30):
        await eval_async(
            _plain("parent", add_child_and_watch(_boxed("child"), {})),
            model="mockllm/model",
            max_tasks=2,
            task_retry_attempts=retries,
        )
    attempts = await _agreed_attempts(lifecycle, tmp_path / "logs")
    assert attempts == sorted(expected + [("parent", "success")])


async def test_abort_while_waiting_for_a_slot_after_setup(
    tmp_path: Path, lifecycle: _Lifecycle, monkeypatch: pytest.MonkeyPatch
) -> None:
    # max_tasks=1: the parent holds the slot, the child sets up in the lane and
    # waits for the slot; aborted there, it ends as any started task does
    import inspect_ai._eval.run as run_module

    waiting = anyio.Event()
    real_take_slot = run_module._LaneAttempt.take_slot

    async def take_slot(self: Any) -> None:
        waiting.set()
        await real_take_slot(self)

    monkeypatch.setattr(run_module._LaneAttempt, "take_slot", take_slot)

    @solver
    def abort_waiting_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(_boxed("child"), start="when_free")
            with anyio.fail_after(10):
                await waiting.wait()
            cancel = _child_state().task_cancel
            assert cancel is not None
            cancel.cancel_task("abort")
            with anyio.fail_after(10):
                while _child_state().completed_at is None:
                    await anyio.sleep(0.01)
            return state

        return solve

    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", abort_waiting_child()), model="mockllm/model", max_tasks=1
        )
    assert _statuses(logs) == [("parent", "success"), ("child", "error")]
    error = logs[1].error
    assert error is not None and "abort" in error.message
    assert await _agreed_attempts(lifecycle, tmp_path / "logs") == [
        ("child", "error"),
        ("parent", "success"),
    ]


async def test_run_cancel_during_setup_beside_a_running_task(
    tmp_path: Path, lifecycle: _Lifecycle
) -> None:
    # the run is cancelled while the child sets up and the parent runs: both
    # started, both end cancelled, as running tasks do
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
    assert await _agreed_attempts(lifecycle, tmp_path / "logs") == [
        ("child", "cancelled"),
        ("parent", "cancelled"),
    ]


# --- the setup lane: setups do not hold task slots --------------------------------


async def test_tasks_waiting_for_setup_hold_no_task_slot(
    tmp_path: Path, lifecycle: _Lifecycle
) -> None:
    # max_tasks=2: the parent holds one slot and adds two sandboxed tasks (each
    # with its own config) and one plain task. The first sandboxed task sets up
    # in the lane; the second waits for the lane without starting; the plain
    # task takes the free slot and finishes during the first setup
    from inspect_ai.util import sandbox_setup

    dirs = {name: tmp_path / name for name in ("box1", "box2")}
    for path in dirs.values():
        path.mkdir()
    plain_done = anyio.Event()
    seen: dict[str, Any] = {}

    async def init() -> None:
        setup = sandbox_setup()
        assert setup is not None
        if setup.task_dir == str(dirs["box1"]):
            with anyio.fail_after(10):
                await plain_done.wait()
            # plain started and ran in the free slot; box2 waits for the lane,
            # not started
            seen["started_during_box1_setup"] = sorted(t for t, _ in lifecycle.starts)
            stats = task_dispatcher_stats()
            assert stats is not None
            seen["pending_during_box1_setup"] = stats.pending

    @solver
    def mark_done() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            plain_done.set()
            return state

        return solve

    @solver
    def add_children() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                [
                    _boxed("box1", dirs["box1"]),
                    _boxed("box2", dirs["box2"]),
                    _plain("plain", mark_done()),
                ],
                start="when_free",
            )
            return state

        return solve

    _box["task_init"] = init
    with anyio.fail_after(30):
        logs = await eval_async(
            _plain("parent", add_children(), _wait_for(plain_done)),
            model="mockllm/model",
            max_tasks=2,
        )
    assert sorted(_statuses(logs)) == [
        ("box1", "success"),
        ("box2", "success"),
        ("parent", "success"),
        ("plain", "success"),
    ]
    assert seen == {
        "started_during_box1_setup": ["box1", "parent", "plain"],
        "pending_during_box1_setup": 1,
    }
    await _agreed_attempts(lifecycle, tmp_path / "logs")


@solver
def _wait_for(event: anyio.Event) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with anyio.fail_after(10):
            await event.wait()
        return state

    return solve


async def test_task_with_no_sandboxed_samples_yet_skips_the_setup_lane(
    tmp_path: Path,
) -> None:
    # a SampleSource task with a sandbox but an empty seed has nothing to set
    # up when it starts, so it starts in a slot while another task sets up in
    # the lane (its added samples start their sandboxes when they arrive)
    a_dir, feed_dir = tmp_path / "a", tmp_path / "feed"
    a_dir.mkdir()
    feed_dir.mkdir()

    async def init() -> None:
        from inspect_ai.util import sandbox_setup

        setup = sandbox_setup()
        assert setup is not None
        if setup.task_dir == str(a_dir):
            # the feed starts while a sets up
            with anyio.fail_after(10):
                while not any(s.task == "feed" for s in get_eval_states()):
                    await anyio.sleep(0.01)

    class _OneLater(SampleSource):
        def __init__(self) -> None:
            self._done = False

        async def next_samples(self) -> list[Sample] | None:
            if self._done:
                return None
            self._done = True
            return [Sample(input="added")]

    feed = Task(name="feed", dataset=_OneLater(), solver=noop(), sandbox="slot_box")
    setattr(feed, TASK_RUN_DIR_ATTR, str(feed_dir))
    _box["task_init"] = init
    with anyio.fail_after(30):
        logs = await eval_async(
            [_boxed("a", a_dir), feed], model="mockllm/model", max_tasks=2
        )
    assert _statuses(logs) == [("a", "success"), ("feed", "success")]
    assert len(_box["inits"]) == 2
