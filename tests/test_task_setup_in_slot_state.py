"""Tasks starting their sandboxes in their slots: provider state, cleanup, output.

Every test sets INSPECT_TASK_SETUP_IN_SLOT=1. A fake provider records, for each
hook, the state of the three patterns providers use: a ContextVar set fresh by
each task_init (Modal, E2B, Daytona), get-or-create on a ContextVar (k8s), and
state on sandbox_lifecycle_state() (docker).
"""

import os
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, overload

import anyio
import pytest
from pydantic import BaseModel
from typing_extensions import override

from inspect_ai import Task, enqueue_task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    sandboxenv,
)
from inspect_ai.util._display import init_display_type
from inspect_ai.util._sandbox.lifecycle import sandbox_lifecycle_state


class BoxConfig(BaseModel, frozen=True):
    name: str


HOOKS: dict[str, Any] = {}
EVENTS: list[tuple[str, ...]] = []

# pattern 1: task_init sets a ContextVar fresh (Modal / E2B / Daytona)
_fresh: ContextVar[str] = ContextVar("r3b_fresh")
# pattern 2: get-or-create on a ContextVar (k8s)
_goc: ContextVar[list[str]] = ContextVar("r3b_goc")


# pattern 3: state on sandbox_lifecycle_state() (docker)
class _Life:
    def __init__(self) -> None:
        self.configs: list[str] = []


def _name(config: SandboxEnvironmentConfigType | None) -> str:
    assert isinstance(config, BoxConfig)
    return config.name


def _states() -> tuple[str, str, str]:
    scope = sandbox_lifecycle_state()
    life = ",".join(scope.get(_Life).configs) if scope is not None else "MISSING"
    goc = _goc.get(None)
    return (
        _fresh.get("MISSING"),
        ",".join(goc) if goc is not None else "MISSING",
        life,
    )


@sandboxenv(name="r3b_box")
class R3bBox(SandboxEnvironment):
    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return BoxConfig(**config)

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        name = _name(config)
        EVENTS.append(("task_init", name))
        hook = HOOKS.get(f"task_init:{name}") or HOOKS.get("task_init")
        if hook is not None:
            await hook(name)
        _fresh.set(name)
        try:
            goc = _goc.get()
        except LookupError:
            goc = []
            _goc.set(goc)
        goc.append(name)
        scope = sandbox_lifecycle_state()
        assert scope is not None
        scope.get(_Life).configs.append(name)
        EVENTS.append(("task_init_done", name))

    @override
    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        EVENTS.append(("task_cleanup", _name(config), *_states()))

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        EVENTS.append(("sample_init", task_name, _name(config), *_states()))
        return {"default": R3bBox()}

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
    HOOKS.clear()
    EVENTS.clear()
    yield
    HOOKS.clear()
    EVENTS.clear()


@solver
def noop() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def spec(config: str) -> SandboxEnvironmentSpec:
    return SandboxEnvironmentSpec("r3b_box", BoxConfig(name=config))


def boxed(name: str, config: str, *solvers: Solver) -> Task:
    return Task(
        name=name,
        dataset=[Sample(input="x", id=1)],
        solver=list(solvers) or noop(),
        sandbox=spec(config),
    )


def two_config_task(name: str, x: str, y: str) -> Task:
    return Task(
        name=name,
        dataset=[
            Sample(input="x", id=1, sandbox=spec(x)),
            Sample(input="x", id=2, sandbox=spec(y)),
        ],
        solver=noop(),
    )


def statuses(logs: list[EvalLog]) -> list[tuple[str, str]]:
    return [(log.eval.task, log.status) for log in logs]


def events(kind: str) -> list[tuple[str, ...]]:
    return [e for e in EVENTS if e[0] == kind]


# --- a partly finished setup -------------------------------------------------------
#
# A task whose samples use configs X and Y: X's task_init finishes, then Y's
# fails (or the task is aborted during it). X is now started, so a later task
# on X takes the "already started" path and gets the run's shared provider
# state. The configs start in set order, which depends on string hashing, so
# each test tries fresh config names until X happens to start first.


async def _x_started_then_y_ended(
    second: Any, *, ending: str, max_tries: int = 12
) -> tuple[str, str, list[EvalLog]]:
    for i in range(max_tries):
        x, y = f"X{i}", f"Y{i}"
        EVENTS.clear()
        HOOKS.clear()
        HOOKS[f"task_init:{y}"] = HOOKS_ENDINGS[ending]
        with anyio.fail_after(30):
            try:
                logs = await eval_async(
                    [two_config_task("t", x, y), second(x)],
                    model="mockllm/model",
                    max_tasks=1,
                    task_retry_attempts=0,
                )
            except RuntimeError:
                pytest.skip("baseline: a seed setup failure fails the run")
        inits = [e[1] for e in events("task_init")]
        if inits[:2] == [x, y]:
            return x, y, logs
    pytest.fail("X never started before Y")


async def _fail(name: str) -> None:
    raise RuntimeError(f"{name} setup failed")


async def _abort(name: str) -> None:
    _abort_running_task()
    await anyio.sleep_forever()


def _abort_running_task() -> None:
    # the latest cancel recorded for this task: earlier tries of a test left
    # theirs behind
    name = _running_task.get()
    CANCELS[len(CANCEL_TASKS) - 1 - CANCEL_TASKS[::-1].index(name)].cancel_task("abort")


HOOKS_ENDINGS = {"fail": _fail, "abort": _abort}
CANCELS: list[Any] = []
# each recorded cancel's task name
CANCEL_TASKS: list[str] = []
_running_task: ContextVar[str] = ContextVar("r3b_running_task")


@pytest.fixture
def record_cancels(monkeypatch: pytest.MonkeyPatch) -> Any:
    import inspect_ai._eval.run as run_module
    from inspect_ai._display.core.display import TaskCancel as real

    real_run_task = run_module._run_task

    async def named_run_task(options: Any, *args: Any, **kwargs: Any) -> Any:
        _running_task.set(options.task.name)
        return await real_run_task(options, *args, **kwargs)

    def recording(*args: Any, **kwargs: Any) -> Any:
        cancel = real(*args, **kwargs)
        CANCELS.append(cancel)
        CANCEL_TASKS.append(_running_task.get())
        hook = HOOKS.get("on_cancel")
        if hook is not None:
            hook()
        return cancel

    monkeypatch.setattr(run_module, "TaskCancel", recording)
    monkeypatch.setattr(run_module, "_run_task", named_run_task)
    CANCELS.clear()
    CANCEL_TASKS.clear()
    yield
    CANCELS.clear()
    CANCEL_TASKS.clear()


@pytest.mark.parametrize("ending", ["fail", "abort"])
async def test_later_task_on_config_started_by_a_failed_setup_gets_its_state(
    record_cancels: Any, ending: str
) -> None:
    # t's setup starts X, then Y fails (or t is aborted during Y's setup); u
    # (config X) runs next. X's task_init ran and its cleanup is registered,
    # so u's samples should see X's provider state (fresh var "X", get-or-create
    # list holding X), as they would had t's setup finished.
    x, y, logs = await _x_started_then_y_ended(lambda x: boxed("u", x), ending=ending)
    assert statuses(logs) == [("t", "error"), ("u", "success")]
    (u_sample,) = [e for e in events("sample_init") if e[1] == "u"]
    _, _, config, fresh, goc, life = u_sample
    assert config == x
    assert fresh == x, u_sample
    assert x in goc.split(","), u_sample


async def test_retry_after_partly_finished_setup_finds_get_or_create_state() -> None:
    # one task (X, Y); Y fails once, the retry starts only Y. A get-or-create
    # provider's retried task_init should find the object X's task_init created
    # (as when one task_init follows another), so the retry's samples and Y's
    # cleanup see one object holding X and Y.
    for i in range(12):
        x, y = f"X{i}", f"Y{i}"
        EVENTS.clear()
        HOOKS.clear()
        calls = {"n": 0}

        async def fail_once(name: str, calls: dict[str, int] = calls) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Y setup failed")

        HOOKS[f"task_init:{y}"] = fail_once
        with anyio.fail_after(30):
            try:
                logs = await eval_async(
                    two_config_task("t", x, y),
                    model="mockllm/model",
                    task_retry_attempts=1,
                )
            except RuntimeError:
                pytest.skip("baseline: a seed setup failure fails the run")
        if [e[1] for e in events("task_init")][:2] == [x, y]:
            break
    else:
        pytest.fail("X never started before Y")
    assert statuses(logs) == [("t", "success")]
    goc_seen = {e[2]: e[4] for e in events("sample_init")}
    assert sorted(goc_seen[x].split(",")) == sorted([x, y]), EVENTS
    assert sorted(goc_seen[y].split(",")) == sorted([x, y]), EVENTS


# --- a task_init that finishes despite a cancellation ----------------------------


async def test_task_init_that_finishes_during_an_abort_is_cleaned_up(
    record_cancels: Any,
) -> None:
    # a provider shields its task_init's resource creation (so it is never left
    # half made); the task is aborted while it runs. task_init returns normally,
    # having created resources, so its task_cleanup must run at the end of the
    # run, once per task_init.
    calls = {"n": 0}

    async def shielded(name: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            with anyio.CancelScope(shield=True):
                _abort_running_task()
                await anyio.sleep(0.2)

    HOOKS["task_init"] = shielded
    with anyio.fail_after(30):
        logs = await eval_async(
            [boxed("a", "S"), boxed("b", "S")], model="mockllm/model", max_tasks=1
        )
    assert statuses(logs) == [("a", "error"), ("b", "success")]
    inits = len(events("task_init_done"))
    cleanups = len(events("task_cleanup"))
    assert (inits, cleanups) == (1, 1), EVENTS


@pytest.mark.parametrize("in_slot", ["1", "0"])
async def test_task_init_that_finishes_during_a_run_cancel_is_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, in_slot: str
) -> None:
    # the same with the run itself cancelled (in_slot=0: the default mode)
    monkeypatch.setenv("INSPECT_TASK_SETUP_IN_SLOT", in_slot)
    entered = anyio.Event()

    async def shielded(name: str) -> None:
        with anyio.CancelScope(shield=True):
            entered.set()
            await anyio.sleep(0.2)

    HOOKS["task_init"] = shielded
    with anyio.fail_after(30):
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:

                async def cancel_when_entered() -> None:
                    await entered.wait()
                    scope.cancel()

                tg.start_soon(cancel_when_entered)
                await eval_async(boxed("a", "S"), model="mockllm/model")
    assert len(events("task_init_done")) == 1
    assert [e[1] for e in events("task_cleanup")] == ["S"], EVENTS


# --- isolation from running tasks ------------------------------------------------


async def test_running_task_unaffected_after_another_task_set_up() -> None:
    # parent (A) adds child (B); after child's setup has finished and its
    # sample has run, parent's sample still sees its own fresh state "A" and
    # no setup scope; child's sample saw "B"
    from inspect_ai.util import sandbox_setup

    child_ran = anyio.Event()
    seen: dict[str, Any] = {}

    @solver
    def child_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            seen["child"] = _states()[0]
            child_ran.set()
            return state

        return solve

    @solver
    def parent_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_task(boxed("child", "B", child_solver()), start="when_free")
            with anyio.fail_after(10):
                await child_ran.wait()
            seen["parent"] = _states()[0]
            seen["setup"] = sandbox_setup()
            return state

        return solve

    with anyio.fail_after(30):
        logs = await eval_async(
            boxed("parent", "A", parent_solver()), model="mockllm/model", max_tasks=2
        )
    assert statuses(logs) == [("parent", "success"), ("child", "success")]
    assert seen == {"child": "B", "parent": "A", "setup": None}
    cleanups = {e[1]: e[2] for e in events("task_cleanup")}
    assert cleanups == {"A": "A", "B": "B"}


async def test_task_on_a_config_being_set_up_waits_unstarted(
    record_cancels: Any,
) -> None:
    # a's setup of W runs; b (also W) has setup to do too, so it waits for the
    # setup lane without starting (it holds no slot, though one is free). a's
    # setup then finishes, both run, and W is set up and cleaned up once
    from inspect_ai._control.max_tasks import task_dispatcher_stats

    seen: dict[str, Any] = {}

    async def record(name: str) -> None:
        # the tasks started so far (each start creates its TaskCancel)
        seen["started"] = list(CANCEL_TASKS)
        stats = task_dispatcher_stats()
        assert stats is not None
        seen["in_flight, pending"] = (stats.in_flight, stats.pending)

    HOOKS["task_init"] = record
    with anyio.fail_after(30):
        logs = await eval_async(
            [boxed("a", "W"), boxed("b", "W")], model="mockllm/model", max_tasks=2
        )
    assert statuses(logs) == [("a", "success"), ("b", "success")]
    assert seen == {"started": ["a"], "in_flight, pending": (1, 1)}
    assert len(events("task_init_done")) == 1
    assert [e[1] for e in events("task_cleanup")] == ["W"]


# --- Ctrl-C while one task runs and another sets up -------------------------------

_CTRL_C_SCRIPT = """
import os, signal, sys, tempfile
import anyio
from inspect_ai import Task, eval
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, hooks
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.solver import solver
import test_task_setup_in_slot_state as t

os.environ["INSPECT_TASK_SETUP_IN_SLOT"] = "1"
STATE = {}
STARTS = []
STATES = {}


@hooks("ctrl_c_lifecycle", description="Records task starts and eval states")
class Lifecycle(Hooks):
    async def on_task_start(self, data):
        STARTS.append(data.eval_id)

    async def on_run_end(self, data):
        STATES.update(
            (s.eval_id, s.completed_at is not None) for s in get_eval_states()
        )


def started():
    return STATE.setdefault("e", anyio.Event())


@solver
def wait_forever():
    async def solve(state, generate):
        started().set()
        await anyio.sleep_forever()
        return state
    return solve


async def interrupt(name):
    # once a's sample is running (a has no sandbox, so no setup)
    await started().wait()
    signal.raise_signal(signal.SIGINT)
    await anyio.sleep_forever()


t.HOOKS["task_init:B"] = interrupt
log_dir = tempfile.mkdtemp()
try:
    eval(
        [Task(name="a", dataset=[Sample(input="x")], solver=wait_forever()), t.boxed("b", "B")],
        model="mockllm/model",
        max_tasks=2,
        log_dir=log_dir,
        display="plain",
        ctl_server=False,
    )
except KeyboardInterrupt as ex:
    assert type(ex) is KeyboardInterrupt, repr(ex)
logs = [read_eval_log(i.name) for i in list_eval_logs(log_dir)]
on_disk = sorted((log.eval.task, log.status) for log in logs)
print("ON_DISK", on_disk, flush=True)
print("EVENTS", t.EVENTS, flush=True)
print("STARTS", STARTS, "STATES", STATES, flush=True)
assert on_disk == [("a", "cancelled"), ("b", "cancelled")], on_disk
# both started (hook, control channel) and their eval states finished
assert sorted(STARTS) == sorted(log.eval.eval_id for log in logs)
assert STATES == {eval_id: True for eval_id in STARTS}, STATES
# the interrupted setup registered no cleanup
assert [e for e in t.EVENTS if e[0] == "task_cleanup"] == [], t.EVENTS
print("OK")
"""


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_ctrl_c_during_setup_beside_a_running_task(backend: str) -> None:
    import subprocess as sp

    here = str(Path(__file__).parent)
    env = {
        **os.environ,
        "INSPECT_ASYNC_BACKEND": backend,
        "PYTHONPATH": here + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    result = sp.run(
        [sys.executable, "-c", _CTRL_C_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-5000:]
    assert "OK" in result.stdout


# --- collected setup output ----------------------------------------------------------


async def test_collected_setup_output_keeps_multibyte_characters(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # a setup subprocess writes 3-byte characters across a 64 KiB pipe read,
    # then fails: the output shown with the error has every character intact
    # (no U+FFFD where a read split a character). Baseline: the output goes
    # to the terminal, which shows it intact
    from inspect_ai.util import subprocess

    async def fail(name: str) -> None:
        await subprocess(
            [sys.executable, "-c", "import sys; sys.stdout.write('€' * 22000)"],
            capture_output=False,
        )
        raise RuntimeError("setup failed")

    HOOKS["task_init"] = fail
    with anyio.fail_after(30):
        try:
            logs = await eval_async(boxed("t", "T"), model="mockllm/model")
        except RuntimeError:
            out = capfd.readouterr().out
            assert "�" not in out and "€" * 100 in out
            return
    error = logs[0].error
    assert error is not None
    assert "€" * 100 in error.traceback
    assert "�" not in error.traceback


# --- a TaskSource and a task aborted or failing in its setup ----------------------


@pytest.mark.parametrize("ending", ["fail", "abort", "retry"])
async def test_task_source_hears_a_task_ended_in_its_setup(
    record_cancels: Any, ending: str
) -> None:
    # a TaskSource's seed task ends in its setup (fails, is aborted, or asks
    # for a retry); task_complete hears every attempt, and the follow-up it
    # returns runs
    from inspect_ai import TaskSource

    heard: list[tuple[str, str]] = []
    calls = {"n": 0}

    async def end_first(name: str) -> None:
        calls["n"] += 1
        if calls["n"] > 1:
            return
        if ending == "fail":
            raise RuntimeError("setup failed")
        CANCELS[CANCEL_TASKS.index(_running_task.get())].cancel_task(ending)
        await anyio.sleep_forever()

    HOOKS["task_init:E"] = end_first

    class Source(TaskSource):
        def initial_tasks(self) -> list[Task]:
            return [boxed("seed", "E")]

        async def task_complete(self, log: EvalLog) -> list[Task] | None:
            heard.append((log.eval.task, log.status))
            # one follow-up, after the seed's first attempt
            return [boxed("follow", "F")] if len(heard) == 1 else None

    with anyio.fail_after(30):
        logs = await eval_async(Source(), model="mockllm/model", task_retry_attempts=1)
    if ending == "abort":
        # not retried; E's task_init never finished, so it has no cleanup
        assert sorted(heard) == [("follow", "success"), ("seed", "error")]
        assert sorted(statuses(logs)) == [("follow", "success"), ("seed", "error")]
        assert [e[1] for e in events("task_cleanup")] == ["F"]
    else:
        assert sorted(heard) == [
            ("follow", "success"),
            ("seed", "error"),
            ("seed", "success"),
        ]
        assert sorted(statuses(logs)) == [("follow", "success"), ("seed", "success")]
        assert sorted(e[1] for e in events("task_cleanup")) == ["E", "F"]
