"""Tests for adding tasks to a running eval via `enqueue_task`.

Every run has one task queue and one dispatcher: a task added while the eval
runs starts as soon as a `max_tasks` slot is free, under the same run_id (see
design/task-dispatch.md). Here the trigger is usually a solver (the simplest
in-run caller).
"""

import contextlib
import gc
import threading
import traceback
import types
import weakref
from contextvars import Context, copy_context
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar, Iterator, Literal, cast

import anyio
import anyio.from_thread
import anyio.lowlevel
import anyio.to_thread
import pytest

from inspect_ai import (
    Epochs,
    Task,
    TaskEndedError,
    TaskHandle,
    TaskSource,
    eval,
    eval_async,
    eval_set,
    samples_from_handle,
    task,
    task_with,
)
from inspect_ai._control.eval_state import reset_run_registries
from inspect_ai._display import display
from inspect_ai._display.core import active as active_display_module
from inspect_ai._display.core.display import TaskError
from inspect_ai._display.rich.display import RichDisplay
from inspect_ai._display.textual.app import TaskScreenApp
from inspect_ai._display.textual.display import TextualDisplay
from inspect_ai._eval.eval import _resolve_enqueued_tasks
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.enqueue import (
    RunQueue,
    TaskAttempt,
    TaskRecord,
    attempt_scope,
    creator_model,
    enqueue_task,
    get_run_queue,
)
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.run import TaskRunOptions
from inspect_ai._eval.task.store import DiskSampleStore
from inspect_ai._eval.task.tasks import Tasks
from inspect_ai._util._async import current_async_backend
from inspect_ai._util.background import run_in_background
from inspect_ai._util.content import ContentImage
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunStart, hooks
from inspect_ai.log import EvalConfig, EvalLog, EvalSample, read_eval_log
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._generate_config import active_generate_config
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util import SandboxEnvironmentConfigType, sandboxenv
from inspect_ai.util._display import init_display_type
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment


@task
def child() -> Task:
    return Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[generate()],
        name="child",
    )


@solver
def enqueue_child():
    """A solver that adds a `child` task to the running eval, once."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        enqueue_task(child())
        return state

    return solve


def test_enqueue_task_runs_added_task_in_same_run() -> None:
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    logs = eval(parent, model="mockllm/model", display="none")

    # the enqueued child ran alongside the parent, in the same run
    assert sorted(log.eval.task for log in logs) == ["child", "parent"]
    assert all(log.status == "success" for log in logs)
    assert len({log.eval.run_id for log in logs}) == 1


def test_enqueue_task_chains_across_batches() -> None:
    # each task enqueues the next up to a depth, exercising repeated draining:
    # parent -> gen1 -> gen2, all under one run
    seen: list[str] = []

    @solver
    def spawn_next(depth: int):
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen.append(state.metadata.get("name", "?"))
            if depth > 0:
                enqueue_task(
                    Task(
                        dataset=[Sample(input="hi", target="ok")],
                        solver=[spawn_next(depth - 1)],
                        name=f"gen{depth - 1}",
                        metadata={"name": f"gen{depth - 1}"},
                    )
                )
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[spawn_next(2)],
        name="parent",
        metadata={"name": "parent"},
    )

    logs = eval(parent, model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "parent"]
    assert len({log.eval.run_id for log in logs}) == 1


def test_enqueued_task_media_is_inline_only(tmp_path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def child_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            assert not isinstance(state.input, str)
            content = state.input[0].content
            assert isinstance(content, list)
            image = content[0]
            assert isinstance(image, ContentImage)
            seen.append(image.image)
            return state

        return solve

    @solver
    def enqueue_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(
                Task(
                    dataset=[
                        Sample(
                            id="child",
                            input=[
                                ChatMessageUser(
                                    content=[ContentImage(image=str(secret))]
                                )
                            ],
                        )
                    ],
                    solver=child_solver(),
                    name="child-media",
                )
            )
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="parent", input="parent")],
            solver=enqueue_child(),
            name="parent-media",
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen == [str(secret)]
    child_sample = next(
        sample for log in logs for sample in (log.samples or []) if sample.id == "child"
    )
    content = child_sample.messages[-1].content
    assert isinstance(content, list)
    image = content[0]
    assert isinstance(image, ContentImage)
    assert image.image == str(secret)


def test_enqueued_resolved_task_media_is_inline_only(tmp_path) -> None:
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"runtime-selected")
    seen: list[str] = []

    @solver
    def child_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            assert not isinstance(state.input, str)
            content = state.input[0].content
            assert isinstance(content, list)
            image = content[0]
            assert isinstance(image, ContentImage)
            seen.append(image.image)
            return state

        return solve

    child = Task(
        dataset=[
            Sample(
                id="child",
                input=[ChatMessageUser(content=[ContentImage(image=str(secret))])],
            )
        ],
        solver=child_solver(),
        name="child-resolved-media",
    )
    resolved_child = resolve_tasks(
        child,
        {},
        get_model("mockllm/model"),
        None,
        None,
        None,
    )[0]
    assert resolved_child.input_media_policy == "inline_only"

    @solver
    def enqueue_resolved_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(resolved_child)
            return state

        return solve

    eval(
        Task(
            dataset=[Sample(id="parent", input="parent")],
            solver=enqueue_resolved_child(),
            name="parent-resolved-media",
        ),
        model="mockllm/model",
        display="none",
    )

    assert seen == [str(secret)]
    assert resolved_child.input_media_policy == "inline_only"


def test_enqueue_task_does_not_leak_active_model() -> None:
    # enqueue_task() resolves the added task by calling init_active_model(),
    # which sets the active model and the run's generate config. That
    # resolution must not leak into the caller: a solver must still see its
    # own model and generate config after enqueuing. The parent's own
    # generate config makes the leak observable (resolution activates the
    # run's config, which does not have it).
    mismatches: list[tuple[str, str]] = []

    @solver
    def enqueue_and_check():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            before = f"{get_model()} {active_generate_config()}"
            enqueue_task(child())
            after = f"{get_model()} {active_generate_config()}"
            if before != after:
                mismatches.append((before, after))
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_and_check()],
        name="parent",
        config=GenerateConfig(temperature=0.5),
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")
    assert mismatches == [], f"active model leaked after enqueue_task: {mismatches}"
    assert all(log.status == "success" for log in logs)


def test_enqueue_task_outside_run_raises() -> None:
    with pytest.raises(RuntimeError, match="while an eval is running"):
        enqueue_task(child())


class _EnqueueOnRunStart(Hooks):
    add: ClassVar[list[Callable[[], Task]]] = []
    returned: ClassVar[list[bool]] = []

    async def on_run_start(self, data: RunStart) -> None:
        enqueue_task(self.add[0]())
        self.returned.append(True)


@contextlib.contextmanager
def _enqueue_on_run_start(add: Callable[[], Task]) -> Iterator[list[bool]]:
    """Register a hook that adds ``add()`` at run start; yields its returns."""

    @hooks("enqueue_on_run_start", description="adds a task at run start")
    def enqueue_on_run_start() -> type[Hooks]:
        return _EnqueueOnRunStart

    _EnqueueOnRunStart.add = [add]
    _EnqueueOnRunStart.returned = []
    try:
        yield _EnqueueOnRunStart.returned
    finally:
        del _registry["hooks:enqueue_on_run_start"]


def test_enqueue_task_from_run_start_hook_starts_after_the_seed() -> None:
    with _enqueue_on_run_start(child):
        logs = eval(
            Task(dataset=[Sample(input="hi")], solver=[generate()], name="parent"),
            model="mockllm/model",
            display="none",
        )

    assert [log.eval.task for log in logs] == ["parent", "child"]
    assert all(log.status == "success" for log in logs)
    assert len({log.eval.run_id for log in logs}) == 1


async def test_task_added_from_run_start_hook_is_freed_once_it_ends(
    tmp_path: Path,
) -> None:
    # the hook's task has no other owner, so it and its dataset are freed
    # once it ends, while the run waits on the source for more
    refs: list[weakref.ref[Any]] = []
    alive_during_next_pull: list[bool] = []

    def hooked() -> Task:
        added = Task(dataset=[Sample(input="x")], solver=[], name="hooked")
        refs.extend([weakref.ref(added), weakref.ref(added.dataset)])
        return added

    class _Src(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(dataset=[Sample(input="x")], solver=[], name="seed")]

        async def next_tasks(self) -> list[Task] | None:
            assert _record("hooked").phase == "ended"
            gc.collect()
            alive_during_next_pull.extend(ref() is not None for ref in refs)
            return None

    init_display_type("none")
    with _enqueue_on_run_start(hooked):
        logs = await eval_async(
            _Src(), model="mockllm/model", log_dir=str(tmp_path), max_tasks=2
        )
    assert [log.eval.task for log in logs] == ["seed", "hooked"]
    assert alive_during_next_pull == [False, False]


@pytest.mark.parametrize("max_tasks", [1, 2])
@pytest.mark.parametrize("added", [False, True])
def test_returned_log_order(added: bool, max_tasks: int) -> None:
    # several definitions and models, with tasks added from on_run_start after
    # the seed: dispatch is sequence-major, so at max_tasks=1 each
    # definition's models start before the next definition's and the logs
    # come back in that order; at max_tasks=2 they come back in the order the
    # tasks were requested
    started: list[tuple[str, str]] = []

    def order_task(name: str) -> Task:
        async def record() -> None:
            started.append((name, str(get_model())))

        return _hook_task(name, record)

    models = ["mockllm/one", "mockllm/two"]

    def run() -> list[EvalLog]:
        return eval(
            [order_task("A"), order_task("B")],
            model=models,
            max_tasks=max_tasks,
            display="none",
        )

    if added:
        with _enqueue_on_run_start(lambda: order_task("C")):
            logs = run()
    else:
        logs = run()

    definitions = ["A", "B", "C"] if added else ["A", "B"]
    by_definition = [(task, model) for task in definitions for model in models]
    requested = [(task, model) for model in models for task in ["A", "B"]]
    if added:
        requested += [("C", model) for model in models]
    returned = [(log.eval.task, log.eval.model) for log in logs]
    assert all(log.status == "success" for log in logs)
    if max_tasks == 1:
        assert started == by_definition
        assert returned == by_definition
    else:
        assert returned == requested


async def test_enqueue_task_from_run_start_hook_config_error_fails_the_run(
    tmp_path: Path,
) -> None:
    # the hook's call returns; the configuration check runs when dispatch
    # opens, and its error ends the run before any seed task starts
    started: list[str] = []

    async def seed_started() -> None:
        started.append("parent")

    init_display_type("none")
    with _enqueue_on_run_start(
        lambda: _hook_task("child", _noop, epochs=Epochs(1, "at_least_2"))
    ) as returned:
        with pytest.raises(PrerequisiteError):
            await eval_async(
                _hook_task("parent", seed_started),
                model="mockllm/model",
                log_dir=str(tmp_path),
            )

    assert returned == [True]
    assert started == []
    assert list(tmp_path.glob("*.eval")) == []


# -- one queue, one dispatcher (design/task-dispatch.md) -----------------------


@sandboxenv(name="dispatch_probe")
class DispatchProbeSandbox(LocalSandboxEnvironment):
    """A local sandbox whose task_init can be held or made to fail per config."""

    calls: ClassVar[list[str]] = []
    started: ClassVar[dict[str, anyio.Event]] = {}
    hold: ClassVar[dict[str, anyio.Event]] = {}
    failures: ClassVar[dict[str, int]] = {}
    on_task_init: ClassVar[Callable[[], None] | None] = None

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.started = {}
        cls.hold = {}
        cls.failures = {}
        cls.on_task_init = None

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        key = str(config)
        cls.calls.append(f"task_init:{key}")
        if cls.on_task_init is not None:
            cls.on_task_init()
        if key in cls.started:
            cls.started[key].set()
        if key in cls.hold:
            await cls.hold[key].wait()
        if cls.failures.get(key, 0) > 0:
            cls.failures[key] -= 1
            raise RuntimeError(f"task_init failed for {key}")

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        cls.calls.append(f"task_cleanup:{config}")


@pytest.fixture
def probe() -> Iterator[type[DispatchProbeSandbox]]:
    DispatchProbeSandbox.reset()
    init_display_type("none")
    yield DispatchProbeSandbox
    DispatchProbeSandbox.reset()


def _record(name: str) -> TaskRecord:
    queue = get_run_queue()
    assert queue is not None
    return next(r for r in queue.records if r.task == name)


@solver
def run_hook(hook: Callable[[], Awaitable[None]]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await hook()
        return state

    return solve


def _hook_task(name: str, hook: Callable[[], Awaitable[None]], **kwargs: Any) -> Task:
    return Task(
        dataset=[Sample(input="x")], solver=[run_hook(hook)], name=name, **kwargs
    )


async def _noop() -> None:
    pass


def _creator_waiting_for_added(seen: list[bool]) -> Task:
    """A creator that adds a task and waits for it to run."""
    released: list[anyio.Event] = []

    def event() -> anyio.Event:
        # created on the run's own loop
        if not released:
            released.append(anyio.Event())
        return released[0]

    async def release() -> None:
        event().set()

    async def add_and_wait() -> None:
        enqueue_task(_hook_task("added", release))
        with anyio.move_on_after(10):
            await event().wait()
        seen.append(event().is_set())

    return _hook_task("creator", add_and_wait)


async def test_added_task_starts_while_its_creator_runs(tmp_path: Path) -> None:
    # without a TaskSource, an added task used to wait for the whole batch: a
    # creator that waits for the task it added waited forever
    seen: list[bool] = []
    init_display_type("none")
    logs = await eval_async(
        _creator_waiting_for_added(seen),
        model="mockllm/model",
        max_tasks=2,
        log_dir=str(tmp_path),
    )
    assert seen == [True]
    assert sorted(log.eval.task for log in logs) == ["added", "creator"]
    assert all(log.status == "success" for log in logs)


def test_added_task_starts_while_its_creator_runs_in_eval_set(tmp_path: Path) -> None:
    seen: list[bool] = []
    success, logs = eval_set(
        _creator_waiting_for_added(seen),
        log_dir=str(tmp_path),
        model="mockllm/model",
        max_tasks=2,
        display="none",
    )
    assert seen == [True]
    assert success
    assert sorted(log.eval.task for log in logs) == ["added", "creator"]


async def test_queued_task_holds_no_log_until_it_starts(tmp_path: Path) -> None:
    seen: list[tuple[str, str | None]] = []

    async def add_and_check() -> None:
        enqueue_task(_hook_task("child", _noop))
        record = _record("child")
        assert record.options is not None
        seen.append((record.phase, record.options.logger.location))

    init_display_type("none")
    logs = await eval_async(
        _hook_task("parent", add_and_check),
        model="mockllm/model",
        max_tasks=1,
        log_dir=str(tmp_path),
    )
    # at max_tasks=1 the child waits behind its creator, with no log file
    assert seen == [("queued", None)]
    assert [log.status for log in logs] == ["success", "success"]


@pytest.mark.parametrize(
    "case", ["configuration", "duplicate_id", "selection", "unresolvable"]
)
async def test_enqueue_task_errors_raise_at_the_call_and_add_nothing(
    tmp_path: Path, case: str
) -> None:
    raised: list[BaseException] = []
    added: list[int] = []
    resolved_child = resolve_tasks(
        _hook_task("resolved_child", _noop),
        {},
        get_model("mockllm/model"),
        None,
        None,
        None,
    )[0]

    async def add_bad() -> None:
        queue = get_run_queue()
        assert queue is not None
        before = len(queue.records)
        try:
            if case == "configuration":
                enqueue_task(_hook_task("child", _noop, epochs=Epochs(1, "at_least_2")))
            elif case == "duplicate_id":
                enqueue_task([resolved_child, resolved_child])
            elif case == "selection":
                # a static dataset with no sample the selection names
                enqueue_task(
                    Task(dataset=[Sample(id=1, input="x")], name="B", solver=[])
                )
            else:
                enqueue_task(
                    Task(dataset=[Sample(input="x")], sandbox="not-registered")
                )
        except Exception as ex:
            raised.append(ex)
        added.append(len(queue.records) - before)

    init_display_type("none")
    logs = await eval_async(
        _hook_task("parent", add_bad),
        model="mockllm/model",
        log_dir=str(tmp_path),
        sample_id=["parent:1", "B:5"] if case == "selection" else None,
    )
    assert [log.eval.task for log in logs] == ["parent"]
    assert added == [0]
    [error] = raised
    expected = {
        "configuration": PrerequisiteError,
        "duplicate_id": ValueError,
        "selection": PrerequisiteError,
        "unresolvable": ValueError,
    }[case]
    assert isinstance(error, expected), repr(error)


async def test_enqueue_task_off_the_run_loop(tmp_path: Path) -> None:
    errors: list[str] = []

    def in_worker() -> None:
        # a worker thread that copied the run's context
        try:
            enqueue_task(_hook_task("no_loop", _noop))
        except RuntimeError as ex:
            errors.append(str(ex))

        async def own_loop() -> None:
            enqueue_task(_hook_task("own_loop", _noop))

        try:
            anyio.run(own_loop)
        except RuntimeError as ex:
            errors.append(str(ex))

        # the supported way from a worker
        anyio.from_thread.run_sync(lambda: enqueue_task(_hook_task("via_loop", _noop)))

    def in_other_thread(token: anyio.lowlevel.EventLoopToken, context: Context) -> None:
        # a thread anyio did not start passes the run's loop token and context
        anyio.from_thread.run_sync(
            context.run, enqueue_task, _hook_task("via_token", _noop), token=token
        )

    async def add_from_threads() -> None:
        await anyio.to_thread.run_sync(in_worker)
        thread = threading.Thread(
            target=in_other_thread,
            args=(anyio.lowlevel.current_token(), copy_context()),
        )
        thread.start()
        await anyio.to_thread.run_sync(thread.join)

    init_display_type("none")
    logs = await eval_async(
        _hook_task("parent", add_from_threads),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )
    assert sorted(log.eval.task for log in logs) == [
        "parent",
        "via_loop",
        "via_token",
    ]
    assert len(errors) == 2
    assert all("event loop" in error for error in errors)


async def test_enqueue_task_after_dispatch_ended_raises(tmp_path: Path) -> None:
    resolved: list[str] = []
    late: list[BaseException] = []
    proceed = anyio.Event()
    done = anyio.Event()

    async def outlive_the_run() -> None:
        await proceed.wait()
        try:
            enqueue_task(_hook_task("late", _noop))
        except BaseException as ex:
            late.append(ex)
        done.set()

    async def start_child() -> None:
        queue = get_run_queue()
        assert queue is not None
        original = queue._resolve

        def counting(tasks: Any) -> Any:
            resolved.append("resolve")
            return original(tasks)

        queue._resolve = counting
        tg.start_soon(outlive_the_run)

    init_display_type("none")
    async with anyio.create_task_group() as tg:
        logs = await eval_async(
            _hook_task("parent", start_child),
            model="mockllm/model",
            log_dir=str(tmp_path),
        )
        proceed.set()
        with anyio.fail_after(10):
            await done.wait()

    assert [log.eval.task for log in logs] == ["parent"]
    [error] = late
    assert isinstance(error, RuntimeError)
    assert "stopped starting tasks" in str(error)
    assert resolved == []


@pytest.mark.parametrize("retries", [0, 2])
async def test_log_init_failure_ends_only_that_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retries: int
) -> None:
    init = TaskLogger.init
    attempts: list[str] = []

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "broken":
            attempts.append(self.eval.eval_id)
            raise OSError("log storage unavailable")
        await init(self)

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    init_display_type("none")
    logs = await eval_async(
        [_hook_task("ok", _noop), _hook_task("broken", _noop)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=retries,
        max_tasks=2,
    )
    by_task = {log.eval.task: log for log in logs}
    assert by_task["ok"].status == "success"
    broken = by_task["broken"]
    assert broken.status == "error"
    assert broken.error is not None
    assert "log storage unavailable" in broken.error.message
    assert broken.location == ""
    # each attempt has its own eval id, and none read a predecessor's location
    assert len(attempts) == retries + 1
    assert len(set(attempts)) == retries + 1


async def test_sandbox_free_task_runs_while_another_task_builds(
    tmp_path: Path, probe: type[DispatchProbeSandbox]
) -> None:
    probe.started["slow"] = anyio.Event()
    probe.hold["slow"] = anyio.Event()
    order: list[str] = []

    async def fast() -> None:
        # the building task holds its slot: the fast task got the other one
        order.append("fast")
        assert _record("building").phase == "attempt"
        probe.hold["slow"].set()

    async def building() -> None:
        order.append("building")

    with anyio.fail_after(30):
        logs = await eval_async(
            [
                _hook_task("building", building, sandbox=("dispatch_probe", "slow")),
                _hook_task("fast", fast),
            ],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=2,
        )
    assert order == ["fast", "building"]
    assert all(log.status == "success" for log in logs)


async def test_setup_failure_ends_only_its_task_and_is_retried(
    tmp_path: Path, probe: type[DispatchProbeSandbox]
) -> None:
    probe.failures["flaky"] = 1
    probe.failures["broken"] = 99

    logs = await eval_async(
        [
            _hook_task("flaky", _noop, sandbox=("dispatch_probe", "flaky")),
            _hook_task("broken", _noop, sandbox=("dispatch_probe", "broken")),
            _hook_task("plain", _noop),
        ],
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
        max_tasks=3,
    )
    by_task = {log.eval.task: log for log in logs}
    assert by_task["flaky"].status == "success"
    assert by_task["plain"].status == "success"
    assert by_task["broken"].status == "error"
    assert by_task["broken"].error is not None
    assert "task_init failed for broken" in by_task["broken"].error.message
    assert probe.calls.count("task_init:flaky") == 2
    assert probe.calls.count("task_init:broken") == 2
    # only the successful setup is cleaned up
    assert [c for c in probe.calls if c.startswith("task_cleanup")] == [
        "task_cleanup:flaky"
    ]


async def test_two_tasks_needing_one_configuration_set_it_up_once(
    tmp_path: Path, probe: type[DispatchProbeSandbox]
) -> None:
    logs = await eval_async(
        [
            _hook_task("a", _noop, sandbox=("dispatch_probe", "shared")),
            _hook_task("b", _noop, sandbox=("dispatch_probe", "shared")),
        ],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
    )
    assert all(log.status == "success" for log in logs)
    assert probe.calls == ["task_init:shared", "task_cleanup:shared"]


async def test_setup_runs_in_the_attempt_after_registration(
    tmp_path: Path, probe: type[DispatchProbeSandbox]
) -> None:
    probe.started["registered"] = anyio.Event()
    probe.hold["registered"] = anyio.Event()
    reached: list[str] = []

    async def observe() -> None:
        await probe.started["registered"].wait()
        reached.append(_record("setup").reached)
        probe.hold["registered"].set()

    logs = await eval_async(
        [
            _hook_task("setup", _noop, sandbox=("dispatch_probe", "registered")),
            _hook_task("observer", observe),
        ],
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=2,
    )
    assert all(log.status == "success" for log in logs)
    # task_init ran after the task registered (and its task-start hooks ran)
    assert reached == ["registered"]


async def test_preview_runs_no_setup(
    tmp_path: Path, probe: type[DispatchProbeSandbox]
) -> None:
    logs = await eval_async(
        _hook_task("preview", _noop, sandbox=("dispatch_probe", "preview")),
        model="mockllm/model",
        log_dir=str(tmp_path),
        run_samples=False,
    )
    assert logs[0].status == "started"
    assert probe.calls == []


async def test_debug_errors_raise_at_every_max_tasks(tmp_path: Path) -> None:
    async def fail() -> None:
        raise ValueError("task error")

    init_display_type("none")
    with pytest.raises(ValueError, match="task error"):
        await eval_async(
            [_hook_task("a", fail), _hook_task("b", _noop)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=2,
            debug_errors=True,
        )


async def test_setup_does_not_hold_a_paged_dataset_in_memory(
    tmp_path: Path,
    probe: type[DispatchProbeSandbox],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the seed samples are streamed to sandbox setup, so samples read back from
    # a dataset paged to disk are freed while task_init runs
    read: list[weakref.ref[Sample]] = []
    alive_during_setup: list[int] = []
    getitem = DiskSampleStore.__getitem__

    def tracking_getitem(self: DiskSampleStore, index: int) -> Sample:
        sample = getitem(self, index)
        read.append(weakref.ref(sample))
        return sample

    def count_alive() -> None:
        gc.collect()
        alive_during_setup.append(sum(1 for ref in read if ref() is not None))

    monkeypatch.setattr(DiskSampleStore, "__getitem__", tracking_getitem)
    probe.on_task_init = count_alive

    logs = await eval_async(
        Task(
            dataset=[Sample(id=i, input="x" * 1000) for i in range(1, 21)],
            solver=[],
            sandbox=("dispatch_probe", "paged"),
            name="paged",
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_dataset_memory=0,
    )
    assert logs[0].status == "success"
    # every sample was read for setup, and none of them is still held
    assert len(read) >= 20
    assert alive_during_setup == [0]


@pytest.fixture
def task_count_changes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Records every change to the displayed task total."""
    init_display_type("none")
    changes: list[int] = []
    display_class = type(display())
    update = display_class.update_task_count

    def recording(self: Any, n: int) -> None:
        changes.append(n)
        update(self, n)

    monkeypatch.setattr(display_class, "update_task_count", recording)
    yield changes


@pytest.mark.parametrize("init_failures,expected", [(99, [-1]), (1, [])])
async def test_task_total_lowered_once_for_a_task_that_never_opened_its_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_count_changes: list[int],
    init_failures: int,
    expected: list[int],
) -> None:
    # a seed task whose log never starts ends before its display row opens,
    # so it comes off the total once; one whose retry opens a row keeps it
    init = TaskLogger.init
    remaining = [init_failures]

    async def failing_init(self: TaskLogger) -> None:
        if self.eval.task == "B" and remaining[0] > 0:
            remaining[0] -= 1
            raise OSError("cannot start log")
        await init(self)

    monkeypatch.setattr(TaskLogger, "init", failing_init)
    logs = await eval_async(
        [_hook_task("A", _noop), _hook_task("B", _noop)],
        model="mockllm/model",
        log_dir=str(tmp_path),
        task_retry_attempts=1,
    )
    statuses = {log.eval.task: log.status for log in logs}
    assert statuses["B"] == ("error" if init_failures > 1 else "success")
    assert task_count_changes == expected


async def test_task_total_for_an_added_task_cancelled_while_queued(
    tmp_path: Path, task_count_changes: list[int]
) -> None:
    async def add_and_cancel() -> None:
        enqueue_task(_hook_task("child", _noop))
        queue = get_run_queue()
        assert queue is not None
        queue.cancel(_record("child"))

    logs = await eval_async(
        _hook_task("parent", add_and_cancel),
        model="mockllm/model",
        log_dir=str(tmp_path),
        max_tasks=1,
    )
    [child] = [log for log in logs if log.eval.task == "child"]
    assert child.status == "error"
    # counted when added, taken off once when it ended without a row
    assert task_count_changes == [1, -1]


async def test_textual_task_total_keeps_a_task_added_while_the_app_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app: Any = TaskScreenApp()
    app._on_load_app = anyio.Event()
    app._on_app_loaded = anyio.Event()
    app._driver = object()
    monkeypatch.setattr(app, "update_display", lambda: None)
    monkeypatch.setattr(app, "refresh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app, "query_one", lambda *args: types.SimpleNamespace(init_tasks=len)
    )
    totals: list[int] = []

    async def open_screen() -> None:
        async with app.task_screen([object()], parallel=True):
            totals.append(app._total_tasks)

    async with anyio.create_task_group() as tg:
        tg.start_soon(open_screen)
        # the screen waits for the app to load; a task is added meanwhile
        await app._on_load_app.wait()
        app.update_task_count(1)
        app._on_app_loaded.set()

    # the seed task and the added one
    assert totals == [2]


async def test_ending_a_record_twice_lowers_the_task_total_once(
    task_count_changes: list[int],
) -> None:
    queue = RunQueue("run", lambda tasks: [], [])
    queue.open(
        lambda resolved, names: [
            cast(
                TaskRunOptions,
                types.SimpleNamespace(
                    logger=types.SimpleNamespace(
                        eval=types.SimpleNamespace(
                            eval_id="e", task="t", task_id=task.id, run_id="run"
                        )
                    ),
                    config=EvalConfig(),
                ),
            )
            for task in resolved
        ],
        task_retry_attempts=0,
    )
    [resolved] = resolve_tasks(
        _hook_task("t", _noop), {}, get_model("mockllm/model"), None, None, None
    )
    try:
        [record] = queue.add([resolved], seed=True)
        queue.screen_open = True
        queue.end(record, None)
        queue.end(record, None)
        assert task_count_changes == [-1]
    finally:
        reset_run_registries()


@solver
def raise_chained() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        try:
            raise KeyError("inner cause")
        except KeyError as ex:
            raise ValueError("task failed") from ex

    return solve


@pytest.mark.parametrize("display_kind", ["rich", "textual"])
async def test_ended_tasks_are_released_while_their_rows_are_held(
    tmp_path: Path,
    probe: type[DispatchProbeSandbox],
    monkeypatch: pytest.MonkeyPatch,
    display_kind: str,
) -> None:
    # the task screen holds every row for the whole run: a task that ended (by
    # finishing, cancelled while queued, exhausting its retries on a task
    # error, or failing sandbox setup) releases its Task and dataset while its
    # row, with a failed task's rendered traceback, is still held
    probe.failures["setup_fails"] = 99
    task_refs: dict[str, weakref.ref[Task]] = {}
    dataset_refs: dict[str, weakref.ref[Any]] = {}
    alive: list[str] = []
    rows: list[tuple[str, str]] = []

    def add(name: str, **kwargs: Any) -> None:
        task = Task(dataset=[Sample(input="x")], name=name, **kwargs)
        task_refs[name] = weakref.ref(task)
        dataset_refs[name] = weakref.ref(task.dataset)
        enqueue_task(task)

    async def creator() -> None:
        queue = get_run_queue()
        assert queue is not None
        add("finishes", solver=[], sandbox=("dispatch_probe", "ok"))
        add("cancelled_queued", solver=[])
        queue.cancel(_record("cancelled_queued"))
        add("task_error", solver=[raise_chained()])
        add("setup_error", solver=[], sandbox=("dispatch_probe", "setup_fails"))
        with anyio.fail_after(30):
            for name in task_refs:
                await _record(name).ended.wait()
        gc.collect()
        alive.extend(
            name
            for name in task_refs
            if task_refs[name]() is not None or dataset_refs[name]() is not None
        )
        # the failed rows are still held, with their tracebacks
        active = display()
        held: list[Any]
        if isinstance(active, TextualDisplay):
            held = active.app._app_tasks
        else:
            assert isinstance(active, RichDisplay)
            held = active.tasks
        for row in held:
            if isinstance(row.result, TaskError):
                rows.append((row.profile.name, row.result.text))
        # the successful setup stays registered for the run's cleanup
        assert "task_cleanup:ok" not in probe.calls

    async def run() -> list[EvalLog]:
        return await eval_async(
            _hook_task("creator", creator),
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=2,
            task_retry_attempts=1,
        )

    if display_kind == "textual":
        if current_async_backend() != "asyncio":
            pytest.skip("the Textual app runs on asyncio")
        app: TaskScreenApp[None] = TaskScreenApp()
        textual = TextualDisplay()
        # TextualDisplay.run_task_app sets this when it runs the app itself
        setattr(textual, "app", app)
        # the headless test driver cannot suspend the app around setup
        monkeypatch.setattr(
            TextualDisplay, "suspend_task_app", lambda self: contextlib.nullcontext()
        )
        monkeypatch.setattr(active_display_module, "_active_display", textual)
        async with app.run_test():
            logs = await run()
    else:
        logs = await run()
    assert alive == []
    statuses = {log.eval.task: log.status for log in logs}
    assert statuses == {
        "creator": "success",
        "finishes": "success",
        "cancelled_queued": "error",
        "task_error": "error",
        "setup_error": "error",
    }
    failed = dict(rows)
    assert "KeyError: 'inner cause'" in failed["task_error (retry 1 of 1)"]
    assert "ValueError: task failed" in failed["task_error (retry 1 of 1)"]
    assert "task_init failed for setup_fails" in failed["setup_error (retry 1 of 1)"]
    assert "task_cleanup:ok" in probe.calls


# -- tasks added inside a running task resolve under its model (#6641) ---------


def _child_models(logs: list[EvalLog], name: str = "child") -> list[str]:
    return sorted(log.eval.model for log in logs if log.eval.task == name)


def test_enqueue_task_in_multi_model_eval_adds_one_per_creator() -> None:
    # each creator adds one child, on its own model (not one per run model)
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    assert all(log.status == "success" for log in logs)
    assert _child_models(logs) == ["mockllm/model", "mockllm/model2"]


def test_enqueue_task_keeps_added_task_model() -> None:
    child_with_model = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[generate()],
        name="child",
        model="mockllm/own",
    )

    @solver
    def enqueue_child_with_model() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(child_with_model)
            return state

        return solve

    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child_with_model()],
        name="parent",
    )

    logs = eval(parent, model=["mockllm/model", "mockllm/model2"], display="none")

    assert all(log.status == "success" for log in logs)
    assert _child_models(logs) == ["mockllm/own", "mockllm/own"]


def test_enqueue_task_under_eval_set_uses_creator_model(tmp_path: Path) -> None:
    # eval_set() runs its tasks in an eval whose model is `none`; an added task
    # that sets no model runs on its creator's model instead of failing
    parent = Task(
        dataset=[Sample(input="hi", target="ok")],
        solver=[enqueue_child()],
        name="parent",
    )

    success, logs = eval_set(
        parent,
        model=["mockllm/model", "mockllm/model2"],
        log_dir=str(tmp_path),
        display="none",
    )

    assert _child_models(logs) == ["mockllm/model", "mockllm/model2"]
    assert success
    for log in logs:
        if log.eval.task != "child":
            continue
        child_log = read_eval_log(log.location)
        assert child_log.status == "success"
        assert child_log.samples is not None
        # generate() returned model output (the none model raises instead);
        # mockllm's default output names mockllm/model for every model
        assert (
            child_log.samples[0].output.completion
            == "Default output from mockllm/model"
        )


def test_task_source_additions_resolve_per_run_model() -> None:
    # tasks a TaskSource callback returns, and tasks enqueue_task() adds from
    # inside a callback, resolve once per run model, even though the sample
    # callbacks run inside the creator's attempt
    def added(name: str) -> Task:
        return Task(dataset=[Sample(input="hi", target="ok")], solver=[], name=name)

    class Source(TaskSource):
        def __init__(self) -> None:
            self.pulled = False

        def initial_tasks(self) -> list[Task]:
            return [
                Task(dataset=[Sample(input="hi", target="ok")], solver=[], name="seed")
            ]

        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            if task.name != "seed":
                return None
            enqueue_task(added("enqueued_in_sample_complete"))
            return [added("returned_by_sample_complete")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if log.eval.task != "seed":
                return None
            enqueue_task(added("enqueued_in_task_complete"))
            return [added("returned_by_task_complete")]

        async def next_tasks(self) -> list[Task] | None:
            if self.pulled:
                return None
            self.pulled = True
            enqueue_task(added("enqueued_in_next_tasks"))
            return [added("returned_by_next_tasks")]

    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(Source(), model=models, display="none")

    assert all(log.status == "success" for log in logs)
    # two seed attempts (one per model), each adding once per run model
    per_seed = sorted(models * 2)
    assert _child_models(logs, "enqueued_in_sample_complete") == per_seed
    assert _child_models(logs, "returned_by_sample_complete") == per_seed
    assert _child_models(logs, "enqueued_in_task_complete") == per_seed
    assert _child_models(logs, "returned_by_task_complete") == per_seed
    # next_tasks() is called once
    assert _child_models(logs, "enqueued_in_next_tasks") == models
    assert _child_models(logs, "returned_by_next_tasks") == models


def test_sample_abandoned_additions_resolve_per_run_model() -> None:
    # sample_abandoned runs inside the creator's attempt, like
    # sample_complete; tasks it returns or enqueues still resolve once per run
    # model. Each seed (one per model) cancels its parked sibling sample.
    from inspect_ai._control.cancel import cancel_sample
    from inspect_ai.log._samples import sample_active

    def added(name: str) -> Task:
        return Task(dataset=[Sample(input="hi", target="ok")], solver=[], name=name)

    async def on_abandoned(sample: Sample, epoch: int, task: Task) -> list[Task]:
        enqueue_task(added("enqueued_in_sample_abandoned"))
        return [added("returned_by_sample_abandoned")]

    @solver
    def cancel_parked_sibling() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            active = sample_active()
            assert active is not None
            parked = "b" if state.sample_id == "a" else "a"
            with anyio.fail_after(60):
                while True:
                    probe = await cancel_sample(
                        active.eval_id, parked, 1, action="cancel", dry_run=True
                    )
                    if probe is not None and probe.get("status") == "cancelled":
                        break
                    await anyio.sleep(0.01)
            result = await cancel_sample(active.eval_id, parked, 1, action="cancel")
            assert result is not None
            assert result["ok"] is True and result["changed"] is True
            return state

        return solve

    source = TaskSource.from_tasks(
        [
            Task(
                dataset=[Sample(id="a", input="x"), Sample(id="b", input="x")],
                solver=cancel_parked_sibling(),
                name="seed",
            )
        ],
        sample_abandoned=on_abandoned,
    )
    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(tasks=source, model=models, display="none", max_samples=1)

    assert all(log.status == "success" for log in logs)
    # two seed attempts each abandon one sample, each addition once per run model
    per_seed = sorted(models * 2)
    assert _child_models(logs, "enqueued_in_sample_abandoned") == per_seed
    assert _child_models(logs, "returned_by_sample_abandoned") == per_seed


def test_resolve_enqueued_tasks_outside_attempt_resolves_per_run_model() -> None:
    models = [get_model("mockllm/model"), get_model("mockllm/model2")]
    resolved_child = resolve_tasks(child(), {}, models[0], None, None, None)[0]

    def resolve(tasks: Tasks) -> list[str]:
        resolved = _resolve_enqueued_tasks(
            tasks,
            models=models,
            model_roles=None,
            config=GenerateConfig(),
            sandbox=None,
            sample_shuffle=None,
            checkpoint=None,
            cost_limit=None,
        )
        return [str(r.model) for r in resolved]

    # no attempt running: once per run model, as for a ResolvedTask
    assert resolve(child()) == ["mockllm/model", "mockllm/model2"]
    assert resolve(resolved_child) == ["mockllm/model", "mockllm/model"]

    # inside an attempt: once, under the attempt's model
    with attempt_scope(_attempt(models[1])):
        assert resolve(child()) == ["mockllm/model2"]
        assert resolve(resolved_child) == ["mockllm/model"]


def test_enqueue_task_after_creator_attempt_ends_resolves_per_run_model() -> None:
    # a background coroutine started by a creator attempt that adds a task
    # after the attempt has ended is outside any attempt: its task resolves
    # once per run model, not under the ended creator's model
    class Source(TaskSource):
        def __init__(self) -> None:
            self.release: anyio.Event | None = None
            self.all_added: anyio.Event | None = None
            self.added = 0
            self.pulled = False

        def events(self) -> tuple[anyio.Event, anyio.Event]:
            if self.release is None or self.all_added is None:
                self.release, self.all_added = anyio.Event(), anyio.Event()
            return self.release, self.all_added

        def initial_tasks(self) -> list[Task]:
            return [
                Task(
                    dataset=[Sample(input="hi", target="ok")],
                    solver=[defer_enqueue(self)],
                    name="seed",
                )
            ]

        async def next_tasks(self) -> list[Task] | None:
            # called once no attempt runs, so both seed attempts have ended:
            # release the deferred additions, keep the run open until they
            # are in, then return one more task so the run drains them
            if self.pulled:
                return None
            self.pulled = True
            release, all_added = self.events()
            release.set()
            with anyio.fail_after(30):
                await all_added.wait()
            return [Task(dataset=[Sample(input="hi")], solver=[], name="last")]

    @solver
    def defer_enqueue(source: Source) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            release, all_added = source.events()

            async def add_later() -> None:
                with anyio.fail_after(30):
                    await release.wait()
                enqueue_task(child())
                source.added += 1
                if source.added == 2:
                    all_added.set()

            run_in_background(add_later)
            return state

        return solve

    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(Source(), model=models, display="none")

    assert all(log.status == "success" for log in logs)
    # two deferred additions, each once per run model
    assert _child_models(logs) == sorted(models * 2)


def _attempt(model: Any) -> TaskAttempt:
    record = TaskRecord(
        task_id="t",
        task="t",
        model=str(model),
        index=0,
        options=None,
        retries_remaining=0,
    )
    return TaskAttempt(record, model)


def test_creator_model_expires_when_attempt_ends() -> None:
    model = get_model("mockllm/model")

    # a context copied inside the attempt (as a background task's is) sees the
    # attempt end once the dispatcher marks it ended
    attempt = _attempt(model)
    with attempt_scope(attempt):
        copied = copy_context()
        assert copied.run(creator_model) is model
    attempt.end()
    assert copied.run(creator_model) is None

    # clearing it for a callback does not end the enclosing attempt
    attempt = _attempt(model)
    with attempt_scope(attempt):
        with attempt_scope(None):
            assert creator_model() is None
        assert creator_model() is model


# --- task handles (design/task-handles.md) ----------------------------------


class _Events(dict[str, anyio.Event]):
    """Events by name, each created on first use (on the run's loop)."""

    def __missing__(self, key: str) -> anyio.Event:
        event = anyio.Event()
        self[key] = event
        return event


EVENTS = _Events()


@pytest.fixture
def events() -> Iterator[_Events]:
    EVENTS.clear()
    init_display_type("none")
    yield EVENTS
    EVENTS.clear()


@solver
def rollout_solver() -> Solver:
    """Runs a sent sample as its metadata says: signal, wait, raise."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if "started" in state.metadata:
            EVENTS[state.metadata["started"]].set()
        if "wait" in state.metadata:
            await EVENTS[state.metadata["wait"]].wait()
        if state.metadata.get("raise"):
            raise ValueError("rollout failed")
        return state

    return solve


@task
def rollout_task(fail_on_error: bool = False) -> Task:
    return Task(
        dataset=samples_from_handle(),
        solver=[rollout_solver()],
        fail_on_error=fail_on_error,
        name="rollout_task",
    )


@solver
def searcher(n_steps: int = 3, fail_at: int = -1) -> Solver:
    """The overview's searcher: sends `n_steps` samples and records their runs."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [handle] = enqueue_task(rollout_task())
        runs: list[EvalSample] = []
        async with handle as rollouts:
            try:
                for step in range(n_steps):
                    sample = Sample(
                        input=f"step {step}", metadata={"raise": step == fail_at}
                    )
                    runs.append(await rollouts.enqueue_sample(sample))
            except BaseException:
                rollouts.cancel()
                raise
        state.metadata["runs"] = [[str(r.id), r.error is not None] for r in runs]
        state.metadata["handle_model"] = handle.model
        return state

    return solve


@task
def search(n_steps: int = 3, fail_at: int = -1) -> Task:
    return Task(
        dataset=[Sample(input="search")],
        solver=[searcher(n_steps, fail_at)],
        name="search",
    )


def _send_in_background(handle: TaskHandle, sample: Sample) -> None:
    """Send ``sample`` from a background task, dropping its outcome."""

    async def send() -> None:
        with contextlib.suppress(RuntimeError):
            await handle.enqueue_sample(sample)

    run_in_background(send)


def _by_task(logs: list[EvalLog]) -> dict[str, EvalLog]:
    return {log.eval.task: log for log in logs}


def _creator_task(body: Callable[[], Awaitable[None]], **kwargs: Any) -> Task:
    return _hook_task("creator", body, **kwargs)


def test_search_feeds_a_rollout_task_at_max_tasks_1() -> None:
    logs = eval(search(fail_at=1), model="mockllm/model", display="none", max_tasks=1)
    by_task = _by_task(logs)
    assert by_task["search"].status == "success"
    rollout = by_task["rollout_task"]
    assert rollout.status == "success"
    assert rollout.eval.dataset.name == "samples_from_handle"
    assert rollout.samples is not None and len(rollout.samples) == 3
    assert by_task["search"].samples is not None
    runs = by_task["search"].samples[0].metadata["runs"]
    token = rollout.eval.task_id[:8]
    # each run came back under its sent id; the errored one with its error
    assert runs == [
        [f"send-{token}-0001", False],
        [f"send-{token}-0002", True],
        [f"send-{token}-0003", False],
    ]


def test_search_feeds_a_rollout_task_under_eval_set(tmp_path: Path) -> None:
    success, logs = eval_set(
        search(), log_dir=str(tmp_path), model="mockllm/model", max_tasks=1
    )
    assert success
    assert sorted(log.eval.task for log in logs) == ["rollout_task", "search"]


def test_each_creator_feeds_its_own_rollout_task_in_a_multi_model_run() -> None:
    models = ["mockllm/model", "mockllm/model2"]
    logs = eval(search(), model=models, display="none", max_tasks=1)
    assert all(log.status == "success" for log in logs)
    assert _child_models(logs, "rollout_task") == models
    for log in logs:
        if log.eval.task == "search":
            assert log.samples is not None
            assert log.samples[0].metadata["handle_model"] == log.eval.model


@pytest.mark.parametrize("limit", ["raise", "time_limit", "working_limit"])
async def test_creator_stopping_early_cancels_its_rollouts(
    events: _Events, limit: str
) -> None:
    async def search_body() -> None:
        [handle] = enqueue_task(rollout_task())
        async with handle:
            try:
                _send_in_background(
                    handle,
                    Sample(input="x", metadata={"started": "running", "wait": "never"}),
                )
                await events["running"].wait()
                if limit == "raise":
                    raise ValueError("search failed")
                await anyio.sleep_forever()
            except BaseException:
                handle.cancel()
                raise

    kwargs: dict[str, Any] = {limit: 1} if limit != "raise" else {}
    with anyio.fail_after(30):
        logs = await eval_async(
            _creator_task(search_body, **kwargs), model="mockllm/model"
        )
    by_task = _by_task(logs)
    rollout = by_task["rollout_task"]
    assert rollout.status == "error"
    assert rollout.error is not None and "abort" in rollout.error.message
    creator = by_task["creator"]
    if limit == "raise":
        assert creator.status == "error"
        assert creator.error is not None and "search failed" in creator.error.message
    else:
        assert creator.samples is not None and creator.samples[0].limit is not None
        assert creator.samples[0].limit.type == limit.removesuffix("_limit")


async def test_result_refuses_an_ordinary_added_task(events: _Events) -> None:
    async def body() -> None:
        [handle] = enqueue_task(child())
        with pytest.raises(RuntimeError, match=r"result\(\) waits only on a task"):
            await handle.result()
        # the task is untouched: still queued behind the creator's slot
        assert _record("child").phase == "queued"
        handle.close()
        assert _record("child").phase == "queued"
        handle.cancel()

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model", max_tasks=1)
    by_task = _by_task(logs)
    assert by_task["creator"].status == "success"
    assert by_task["child"].status == "error"


async def test_fed_task_cancelled_while_queued_ends_with_no_log(
    events: _Events, task_count_changes: list[int]
) -> None:
    reports: list[str] = []
    outcomes: list[Any] = []

    async def body() -> None:
        from inspect_ai._control.pause import pause_process, resume_process

        # closed before any sample was sent
        [closed] = enqueue_task(rollout_task())
        outcomes.append(await closed.result())
        # cancelled with no sample sent
        [idle] = enqueue_task(rollout_task())
        idle.cancel()
        outcomes.append(await idle.result())
        # cancelled holding a sent request: a process pause keeps it queued
        await pause_process()
        try:
            [held] = enqueue_task(rollout_task())
            record = _record_by_id(held.task_id)
            async with anyio.create_task_group() as tg:

                async def send() -> None:
                    with pytest.raises(TaskEndedError) as raised:
                        await held.enqueue_sample(Sample(input="x"))
                    outcomes.append(raised.value.log)

                tg.start_soon(send)
                await anyio.wait_all_tasks_blocked()
                assert record.phase == "queued" and record.channel is not None
                assert record.channel.requests
                held.cancel()
            assert not record.abort_requested
            outcomes.append(await held.result())
        finally:
            await resume_process()

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_creator_task(body)]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            reports.append(log.eval.task)
            return None

    with anyio.fail_after(30):
        logs = await eval_async(Source(), model="mockllm/model")
    assert [log.eval.task for log in logs] == ["creator"]
    assert logs[0].status == "success"
    assert outcomes == [None, None, None, None]
    assert reports == ["creator"]
    # each fed task was counted when added and dropped when it ended unstarted
    assert task_count_changes == [1, -1, 1, -1, 1, -1]


def _record_by_id(task_id: str) -> TaskRecord:
    queue = get_run_queue()
    assert queue is not None
    record = queue.find(task_id)
    assert record is not None
    return record


async def test_close_and_async_with_let_running_rollouts_finish(
    events: _Events,
) -> None:
    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        async with handle:
            _send_in_background(
                handle,
                Sample(input="x", metadata={"started": "running", "wait": "go"}),
            )
            await events["running"].wait()
        # closed: the running sample still finishes, then the task ends
        events["go"].set()
        log = await handle.result()
        assert log is not None and log.status == "success"
        assert log.samples is not None and len(log.samples) == 1

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model")
    assert all(log.status == "success" for log in logs)


async def test_handle_send_error_order(events: _Events) -> None:
    async def body() -> None:
        # after close() while a sent sample runs: RuntimeError, then
        # TaskEndedError once the task has ended
        [handle] = enqueue_task(rollout_task())
        _send_in_background(
            handle,
            Sample(input="x", metadata={"started": "a", "wait": "release_a"}),
        )
        await events["a"].wait()
        handle.close()
        with pytest.raises(RuntimeError) as raised:
            await handle.enqueue_sample(Sample(input="y"))
        assert type(raised.value) is RuntimeError
        events["release_a"].set()
        log = await handle.result()
        with pytest.raises(TaskEndedError) as ended:
            await handle.enqueue_sample(Sample(input="y"))
        assert ended.value.log is log

        # cancel() of a running fed task: a send with no await between raises
        # RuntimeError (the record has not ended), then TaskEndedError
        [cancelled] = enqueue_task(rollout_task())
        _send_in_background(
            cancelled,
            Sample(input="x", metadata={"started": "b", "wait": "never"}),
        )
        await events["b"].wait()
        record = _record_by_id(cancelled.task_id)
        cancelled.cancel()
        assert record.phase != "ended"
        with pytest.raises(RuntimeError) as raised:
            await cancelled.enqueue_sample(Sample(input="y"))
        assert type(raised.value) is RuntimeError
        log = await cancelled.result()
        assert log is not None and log.status == "error"
        with pytest.raises(TaskEndedError):
            await cancelled.enqueue_sample(Sample(input="y"))
        cancelled.cancel()
        with pytest.raises(TaskEndedError):
            await cancelled.enqueue_sample(Sample(input="y"))

        # a sample with an id is refused
        [fresh] = enqueue_task(rollout_task())
        with pytest.raises(ValueError):
            await fresh.enqueue_sample(Sample(input="y", id="mine"))
        fresh.close()

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model")
    assert _by_task(logs)["creator"].status == "success"


async def test_each_waiting_sender_gets_its_own_task_ended_error(
    events: _Events,
) -> None:
    ended: dict[str, TaskEndedError] = {}

    async def body() -> None:
        [handle] = enqueue_task(
            task_with(rollout_task(fail_on_error=True), max_samples=1)
        )

        async def send(label: str, metadata: dict[str, Any]) -> None:
            try:
                await handle.enqueue_sample(Sample(input=label, metadata=metadata))
            except TaskEndedError as ex:
                ended[label] = ex

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                send, "a", {"started": "a", "wait": "release_a", "raise": True}
            )
            await events["a"].wait()
            # b and c wait for the only sample slot
            tg.start_soon(send, "b", {})
            tg.start_soon(send, "c", {})
            await anyio.wait_all_tasks_blocked()
            events["release_a"].set()
        log = await handle.result()
        assert log is not None and log.status == "error"
        assert ended["b"].log is log and ended["c"].log is log

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model")
    assert _by_task(logs)["creator"].status == "success"
    assert sorted(ended) == ["b", "c"]
    assert ended["b"] is not ended["c"]
    # neither traceback carries the other sender's frames
    for error in ended.values():
        frames = [
            frame.f_code.co_name for frame, _ in traceback.walk_tb(error.__traceback__)
        ]
        assert frames.count("send") == 1


async def test_send_after_the_creator_ends_raises(events: _Events) -> None:
    kept: list[TaskHandle] = []
    errors: list[BaseException] = []

    async def creator() -> None:
        [handle] = enqueue_task(rollout_task())
        kept.append(handle)
        _send_in_background(
            handle,
            Sample(input="x", metadata={"started": "running", "wait": "release"}),
        )
        await events["running"].wait()

    async def other() -> None:
        # runs until the creator's attempt has ended, the rollout still running
        with anyio.fail_after(20):
            await _record("creator").ended.wait()
        try:
            await kept[0].enqueue_sample(Sample(input="y"))
        except BaseException as ex:
            errors.append(ex)
        events["release"].set()

    with anyio.fail_after(30):
        logs = await eval_async(
            [_creator_task(creator), _hook_task("other", other)],
            model="mockllm/model",
            max_tasks=2,
        )
    assert all(log.status == "success" for log in logs)
    assert len(errors) == 1 and type(errors[0]) is RuntimeError


async def test_drained_fed_task_refuses_sends(events: _Events) -> None:
    from inspect_ai._control.cancel import drain_task

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        _send_in_background(
            handle,
            Sample(input="x", metadata={"started": "running", "wait": "release"}),
        )
        await events["running"].wait()
        drain_task(handle.task_id)
        with pytest.raises(RuntimeError) as raised:
            await handle.enqueue_sample(Sample(input="y"))
        assert type(raised.value) is RuntimeError
        events["release"].set()
        log = await handle.result()
        assert log is not None and log.samples is not None and len(log.samples) == 1
        with pytest.raises(TaskEndedError):
            await handle.enqueue_sample(Sample(input="y"))

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model")
    assert all(log.status == "success" for log in logs)


def test_fed_task_handle_in_next_tasks_after_its_creator_ended() -> None:
    kept: list[TaskHandle] = []
    seen: list[Any] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        kept.append(handle)
        await handle.enqueue_sample(Sample(input="x"))

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_creator_task(body)]

        async def next_tasks(self) -> list[Task] | None:
            if not seen:
                log = await kept[0].result()
                seen.append(log)
                with pytest.raises(TaskEndedError) as raised:
                    await kept[0].enqueue_sample(Sample(input="y"))
                seen.append(raised.value.log)
            return None

    logs = eval(Source(), model="mockllm/model", display="none")
    rollout = _by_task(logs)["rollout_task"]
    assert seen == [rollout, rollout]


def test_fed_task_failing_after_a_sample_is_not_retried() -> None:
    outcomes: list[Any] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task(fail_on_error=True))
        first = await handle.enqueue_sample(Sample(input="x", metadata={"raise": True}))
        outcomes.append(first.error is not None)
        with pytest.raises(TaskEndedError) as raised:
            await handle.enqueue_sample(Sample(input="y"))
        outcomes.append(raised.value.log)

    logs = eval(
        _creator_task(body),
        model="mockllm/model",
        display="none",
        task_retry_attempts=2,
    )
    rollouts = [log for log in logs if log.eval.task == "rollout_task"]
    assert len(rollouts) == 1 and rollouts[0].status == "error"
    assert outcomes[0] is True
    assert (
        outcomes[1] is not None and outcomes[1].eval.task_id == rollouts[0].eval.task_id
    )
    assert _by_task(logs)["creator"].status == "success"


@pytest.mark.parametrize("where", ["task_complete", "sample_complete"])
def test_source_callbacks_cannot_add_a_fed_task(where: str) -> None:
    refused: list[BaseException] = []

    def add() -> list[Task] | None:
        with pytest.raises(RuntimeError) as raised:
            enqueue_task(rollout_task())
        refused.append(raised.value)
        # an ordinary task is still added from the same callback
        enqueue_task(child())
        return None

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [Task(dataset=[Sample(input="x")], name="seed")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            if where == "task_complete" and log.eval.task == "seed":
                return add()
            return None

        async def sample_complete(
            self, sample: EvalSample, task: Task
        ) -> list[Task] | None:
            if where == "sample_complete" and task.name == "seed":
                return add()
            return None

    logs = eval(Source(), model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["child", "seed"]
    assert len(refused) == 1


def test_fed_task_refusals(tmp_path: Path) -> None:
    refused: list[str] = []

    async def body() -> None:
        with pytest.raises(ValueError, match="runs each sample once"):
            enqueue_task(task_with(rollout_task(), epochs=2))
        [resolved] = resolve_tasks(
            rollout_task(), {}, get_model("mockllm/model"), None, None, None
        )
        with pytest.raises(ValueError, match="must start fresh"):
            enqueue_task(resolved)
        refused.append("ok")

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_creator_task(body)]

        async def next_tasks(self) -> list[Task] | None:
            if len(refused) == 1:
                with pytest.raises(RuntimeError, match="inside a task"):
                    enqueue_task(rollout_task())
                refused.append("next_tasks")
                # returned from a callback: refused by the run
                return [rollout_task()]
            return None

    with pytest.raises(RuntimeError, match="inside a task"):
        eval(Source(), model="mockllm/model", display="none", debug_errors=True)
    assert refused == ["ok", "next_tasks"]

    # run on its own
    with pytest.raises(PrerequisiteError, match="takes its samples through"):
        eval(rollout_task(), model="mockllm/model", display="none")
    with pytest.raises(PrerequisiteError, match="takes its samples through"):
        eval_set(rollout_task(), log_dir=str(tmp_path), model="mockllm/model")


def test_fed_task_added_after_its_creator_ended_is_refused() -> None:
    errors: list[BaseException] = []

    async def body() -> None:
        async def add_later() -> None:
            with anyio.fail_after(20):
                await _record("creator").ended.wait()
            try:
                enqueue_task(rollout_task())
            except BaseException as ex:
                errors.append(ex)
            EVENTS["added"].set()

        run_in_background(add_later)

    async def other() -> None:
        with anyio.fail_after(20):
            await EVENTS["added"].wait()

    EVENTS.clear()
    logs = eval(
        [_creator_task(body), _hook_task("other", other)],
        model="mockllm/model",
        display="none",
        max_tasks=2,
    )
    assert sorted(log.eval.task for log in logs) == ["creator", "other"]
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)


async def test_handle_calls_off_the_run_loop(events: _Events) -> None:
    async def body() -> None:
        # off the loop: refused, as enqueue_task() is
        def off_loop() -> None:
            enqueue_task(rollout_task())

        with pytest.raises(RuntimeError, match="event loop"):
            await anyio.to_thread.run_sync(off_loop)

        [handle] = enqueue_task(rollout_task())
        [cancelled] = enqueue_task(rollout_task())
        for method in (handle.close, cancelled.cancel):
            with pytest.raises(RuntimeError, match="event loop") as refused:
                await anyio.to_thread.run_sync(method)
            assert "anyio.from_thread.run_sync()" in str(refused.value)

        # through anyio.from_thread it works, as the error says
        def through_loop() -> list[TaskHandle]:
            anyio.from_thread.run_sync(handle.close)
            anyio.from_thread.run_sync(cancelled.cancel)
            [other] = anyio.from_thread.run_sync(lambda: enqueue_task(rollout_task()))
            assert anyio.from_thread.run(other.result) is None
            return [other]

        await anyio.to_thread.run_sync(through_loop)
        assert _record_by_id(cancelled.task_id).phase == "ended"
        assert await cancelled.result() is None
        assert await handle.result() is None

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model")
    assert [log.eval.task for log in logs] == ["creator"]


SEARCH_FILE = """
from inspect_ai import Task, enqueue_task, samples_from_handle, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, solver


@task
def rollout_task() -> Task:
    return Task(dataset=samples_from_handle(), solver=[], fail_on_error=False)


@solver
def searcher():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        [handle] = enqueue_task(rollout_task())
        async with handle:
            await handle.enqueue_sample(Sample(input="x"))
        return state

    return solve


@task
def search() -> Task:
    return Task(dataset=[Sample(input="search")], solver=[searcher()])
"""


def test_whole_file_with_a_fed_task_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "search.py"
    path.write_text(SEARCH_FILE)
    with pytest.raises(PrerequisiteError, match="rollout_task"):
        eval(str(path), model="mockllm/model", display="none")
    with pytest.raises(PrerequisiteError, match="rollout_task"):
        eval_set(str(path), log_dir=str(tmp_path / "set1"), model="mockllm/model")

    logs = eval(f"{path}@search", model="mockllm/model", display="none")
    assert sorted(log.eval.task for log in logs) == ["rollout_task", "search"]
    success, logs = eval_set(
        f"{path}@search", log_dir=str(tmp_path / "set2"), model="mockllm/model"
    )
    assert success
    assert sorted(log.eval.task for log in logs) == ["rollout_task", "search"]


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_task_hook_adds_a_fed_task_its_samples_feed(
    tmp_path: Path, log_format: Literal["eval", "json"]
) -> None:
    handles: list[TaskHandle] = []

    @hooks(name=f"fed_task_start_hook_{log_format}", description="test")
    class AddOnTaskStart(Hooks):
        async def on_task_start(self, data: Any) -> None:
            if not handles and data.spec.task == "creator":
                [handle] = enqueue_task(rollout_task())
                handles.append(handle)

    async def body() -> None:
        run = await handles[0].enqueue_sample(Sample(input="x"))
        assert run.error is None

    try:
        logs = eval(
            _creator_task(body),
            model="mockllm/model",
            display="none",
            log_dir=str(tmp_path),
            log_format=log_format,
        )
    finally:
        _registry.pop(f"hooks:fed_task_start_hook_{log_format}", None)
    # the channel closed with the creator's attempt, so the rollout ended
    by_task = _by_task(logs)
    assert by_task["rollout_task"].status == "success"
    assert by_task["rollout_task"].samples is not None
    assert len(by_task["rollout_task"].samples) == 1


async def test_fed_task_takes_no_slot(events: _Events) -> None:
    order: list[str] = []

    async def queued() -> None:
        order.append("ordinary")

    async def body() -> None:
        enqueue_task(_hook_task("ordinary", queued))
        [a] = enqueue_task(rollout_task())
        [b] = enqueue_task(rollout_task())
        # two fed tasks run at once while the creator holds the only slot
        async with anyio.create_task_group() as tg:
            for handle, name in ((a, "a"), (b, "b")):
                tg.start_soon(
                    handle.enqueue_sample,
                    Sample(input="x", metadata={"started": name, "wait": "both"}),
                )
            await events["a"].wait()
            await events["b"].wait()
            order.append("fed")
            assert _record("ordinary").phase == "queued"
            events["both"].set()
        a.close()
        b.close()

    with anyio.fail_after(30):
        logs = await eval_async(_creator_task(body), model="mockllm/model", max_tasks=1)
    assert order == ["fed", "ordinary"]
    assert all(log.status == "success" for log in logs)


async def test_sent_sample_setup_failure_ends_the_fed_task(
    tmp_path: Path, probe: type[DispatchProbeSandbox], events: _Events
) -> None:
    probe.failures["sent"] = 99
    outcomes: list[Any] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        first = await handle.enqueue_sample(Sample(input="a"))
        outcomes.append(first.error)
        with pytest.raises(TaskEndedError) as raised:
            await handle.enqueue_sample(
                Sample(input="b", sandbox=("dispatch_probe", "sent"))
            )
        outcomes.append(raised.value.log)

    with anyio.fail_after(30):
        logs = await eval_async(
            _creator_task(body),
            model="mockllm/model",
            log_dir=str(tmp_path),
            task_retry_attempts=2,
        )
    rollouts = [log for log in logs if log.eval.task == "rollout_task"]
    assert len(rollouts) == 1 and rollouts[0].status == "error"
    assert probe.calls.count("task_init:sent") == 1
    assert outcomes[0] is None
    assert outcomes[1] is rollouts[0]


async def test_cancel_while_a_sent_sample_is_held_in_setup(
    tmp_path: Path, probe: type[DispatchProbeSandbox], events: _Events
) -> None:
    probe.started["held"] = anyio.Event()
    probe.hold["held"] = anyio.Event()
    outcomes: list[Any] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())

        async def send(sample: Sample) -> None:
            with pytest.raises(TaskEndedError) as raised:
                await handle.enqueue_sample(sample)
            outcomes.append(raised.value.log)

        async with anyio.create_task_group() as tg:
            tg.start_soon(send, Sample(input="a", sandbox=("dispatch_probe", "held")))
            await probe.started["held"].wait()
            # the feeder is held in the first sample's setup: the second sits
            # in the buffer, unadmitted
            tg.start_soon(send, Sample(input="b"))
            await anyio.wait_all_tasks_blocked()
            handle.cancel()
        record = _record_by_id(handle.task_id)
        assert record.channel is not None and record.channel.requests == {}

    with anyio.fail_after(30):
        logs = await eval_async(
            _creator_task(body), model="mockllm/model", log_dir=str(tmp_path)
        )
    probe.hold["held"].set()
    [rollout] = [log for log in logs if log.eval.task == "rollout_task"]
    assert rollout.status == "error"
    assert outcomes == [rollout, rollout]


class _CancelOnRunStart(Hooks):
    async def on_run_start(self, data: RunStart) -> None:
        [handle] = enqueue_task(child())
        handle.cancel()
        # a task fed through its handle cannot be added outside a task
        with pytest.raises(RuntimeError, match="inside a task"):
            enqueue_task(rollout_task())


def test_handle_cancel_of_a_task_added_at_run_start() -> None:
    @hooks("cancel_on_run_start", description="adds and cancels a task")
    def cancel_on_run_start() -> type[Hooks]:
        return _CancelOnRunStart

    try:
        logs = eval(
            Task(dataset=[Sample(input="hi")], solver=[], name="parent"),
            model="mockllm/model",
            display="none",
        )
    finally:
        del _registry["hooks:cancel_on_run_start"]
    by_task = _by_task(logs)
    assert by_task["parent"].status == "success"
    # cancelled before the run opened: it ends with the abort log
    assert by_task["child"].status == "error"


async def test_fed_task_starts_while_another_task_builds(
    tmp_path: Path, probe: type[DispatchProbeSandbox], events: _Events
) -> None:
    probe.hold["slow"] = anyio.Event()

    async def body() -> None:
        # the other task's task_init is held: the sent sample still runs
        [handle] = enqueue_task(rollout_task())
        async with handle:
            await handle.enqueue_sample(Sample(input="x"))
        assert _record("building").phase == "attempt"
        probe.hold["slow"].set()

    with anyio.fail_after(30):
        logs = await eval_async(
            [
                _hook_task("building", _noop, sandbox=("dispatch_probe", "slow")),
                _creator_task(body),
            ],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=2,
        )
    assert all(log.status == "success" for log in logs)


async def test_sandbox_headroom_for_a_send_can_be_raised_while_it_waits(
    tmp_path: Path, events: _Events
) -> None:
    from inspect_ai._control.limits import process_limits

    returned: list[str] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        async with handle:
            run = await handle.enqueue_sample(Sample(input="x", sandbox="local"))
        returned.append(str(run.id))

    async def operator() -> None:
        with anyio.fail_after(20):
            while not (
                (record := _find_record("rollout_task")) is not None
                and record.phase == "attempt"
            ):
                await anyio.sleep(0.05)
            await anyio.wait_all_tasks_blocked()
        # the creator's sample holds the only sandbox, so its send waits
        assert returned == []
        await process_limits(max_sandboxes=2)

    with anyio.fail_after(30):
        logs = await eval_async(
            [_creator_task(body, sandbox="local"), _hook_task("operator", operator)],
            model="mockllm/model",
            log_dir=str(tmp_path),
            max_tasks=2,
            max_sandboxes=1,
        )
    assert all(log.status == "success" for log in logs)
    assert len(returned) == 1


def _find_record(name: str) -> TaskRecord | None:
    queue = get_run_queue()
    assert queue is not None
    return next((r for r in queue.records if r.task == name), None)


@pytest.mark.parametrize("cancelled_in", ["sample", "task_complete"])
async def test_run_cancellation_keeps_a_fed_tasks_written_log(
    tmp_path: Path, events: _Events, cancelled_in: str
) -> None:
    kept: list[TaskHandle] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        kept.append(handle)
        if cancelled_in == "sample":
            await handle.enqueue_sample(
                Sample(input="x", metadata={"started": "cancel", "wait": "never"})
            )
        else:
            async with handle:
                await handle.enqueue_sample(Sample(input="x"))
            await anyio.sleep_forever()

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_creator_task(body)]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            # the rollout's log is written and taken by the dispatcher; a run
            # cancellation lands while the source hears about it
            if log.eval.task == "rollout_task":
                events["cancel"].set()
                await anyio.sleep_forever()
            return None

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tg:

            async def run() -> None:
                await eval_async(Source(), model="mockllm/model", log_dir=str(tmp_path))

            tg.start_soon(run)
            await events["cancel"].wait()
            tg.cancel_scope.cancel()
        final = await kept[0].result()
    assert final is not None
    expected = "cancelled" if cancelled_in == "sample" else "success"
    assert final.status == expected
    with pytest.raises(TaskEndedError) as raised:
        await kept[0].enqueue_sample(Sample(input="y"))
    assert raised.value.log is final


async def test_log_start_failure_leaves_no_buffered_samples(
    tmp_path: Path, events: _Events, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_start = TaskLogger.log_start

    async def failing_log_start(self: TaskLogger, *args: Any, **kwargs: Any) -> None:
        if self.eval.task == "rollout_task":
            raise OSError("log storage unavailable")
        await log_start(self, *args, **kwargs)

    monkeypatch.setattr(TaskLogger, "log_start", failing_log_start)

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        with pytest.raises(TaskEndedError) as raised:
            await handle.enqueue_sample(Sample(input="x"))
        assert raised.value.log is not None and raised.value.log.status == "error"
        record = _record_by_id(handle.task_id)
        assert record.channel is not None
        assert record.channel.requests == {}
        assert record.channel.enqueuer is None

    with anyio.fail_after(30):
        logs = await eval_async(
            _creator_task(body), model="mockllm/model", log_dir=str(tmp_path)
        )
    assert _by_task(logs)["creator"].status == "success"


async def test_cancel_of_a_fed_attempt_before_it_registers(
    tmp_path: Path, events: _Events, monkeypatch: pytest.MonkeyPatch
) -> None:
    init = TaskLogger.init

    async def held_init(self: TaskLogger) -> None:
        # the rollout's attempt has been picked; hold it before registration
        if self.eval.task == "rollout_task":
            events["picked"].set()
            await events["release_init"].wait()
        await init(self)

    monkeypatch.setattr(TaskLogger, "init", held_init)

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        _send_in_background(handle, Sample(input="x"))
        await events["picked"].wait()
        record = _record_by_id(handle.task_id)
        assert record.phase == "attempt" and record.reached == "added"
        handle.cancel()
        assert not record.ended.is_set()
        with pytest.raises(RuntimeError) as raised:
            await handle.enqueue_sample(Sample(input="y"))
        assert type(raised.value) is RuntimeError
        events["release_init"].set()
        log = await handle.result()
        assert log is not None and log.status == "error"
        with pytest.raises(TaskEndedError):
            await handle.enqueue_sample(Sample(input="y"))

    with anyio.fail_after(30):
        logs = await eval_async(
            _creator_task(body), model="mockllm/model", log_dir=str(tmp_path)
        )
    assert _by_task(logs)["creator"].status == "success"


async def test_fed_request_at_run_cancellation_ends_with_no_log(
    tmp_path: Path, events: _Events
) -> None:
    outcomes: list[Any] = []
    started: list[str] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        try:
            events["waiting"].set()
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            # the waiter sits in this attempt's shielded cleanup while the
            # run's cancellation ends dispatch
            with anyio.CancelScope(shield=True), anyio.fail_after(10):
                try:
                    await handle.enqueue_sample(Sample(input="x"))
                except TaskEndedError as ex:
                    outcomes.append(ex.log)
                outcomes.append(_record_by_id(handle.task_id).reached)
            raise

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [_creator_task(body)]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            started.append(log.eval.task)
            return None

    with anyio.fail_after(30):
        async with anyio.create_task_group() as tg:

            async def run() -> None:
                await eval_async(Source(), model="mockllm/model", log_dir=str(tmp_path))

            tg.start_soon(run)
            await events["waiting"].wait()
            tg.cancel_scope.cancel()
    # the request's task never started: no attempt, no log
    assert outcomes == [None, "added"]
    assert "rollout_task" not in started


def test_fed_tasks_own_retry_request_is_not_honoured() -> None:
    outcomes: list[Any] = []

    async def body() -> None:
        [handle] = enqueue_task(rollout_task())
        _send_in_background(
            handle, Sample(input="x", metadata={"started": "running", "wait": "never"})
        )
        await EVENTS["running"].wait()
        record = _record_by_id(handle.task_id)
        assert record.attempt_cancel is not None
        outcomes.append(record.attempt_cancel.can_retry)
        record.attempt_cancel.request("retry")
        outcomes.append(await handle.result())

    EVENTS.clear()
    logs = eval(
        _creator_task(body),
        model="mockllm/model",
        display="none",
        task_retry_attempts=2,
    )
    rollouts = [log for log in logs if log.eval.task == "rollout_task"]
    assert len(rollouts) == 1 and rollouts[0].status == "error"
    assert outcomes[0] is False
    assert outcomes[1] is not None
    assert outcomes[1].eval.eval_id == rollouts[0].eval.eval_id
