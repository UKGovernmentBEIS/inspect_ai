"""Where a sandbox provider's ``task_init`` state is visible, for seed and added tasks.

Three fake providers mimic the three state patterns published providers use:

- ``ctxvar_fake``: Modal / Daytona / E2B / Vector Podman. ``task_init`` *sets*
  a ContextVar (no default) to fresh state; ``sample_init``, ``sample_cleanup``
  and ``task_cleanup`` read it (a missing value would be a ``LookupError`` in
  those providers; here it is recorded as ``MISSING``).
- ``getorcreate_fake``: the UK AISI k8s provider (``HelmReleaseManager``).
  ``task_init`` calls a get-or-create on a ContextVar, so a second ``task_init``
  in the same context reuses the first one's state.
- ``lifecycle_fake``: Inspect's docker / Lizard / inspect_ranges. State lives on
  ``sandbox_lifecycle_state()``.

Each sample registers its id in the state it sees (as Modal and Daytona append
the sandbox id to their ``_running_sandboxes`` list), and ``task_cleanup``
records which ids its state holds: the ids a provider's end-of-run cleanup
would tear down. Every ``task_cleanup`` runs in the context its own
``task_init`` left, so every sample is reachable from some cleanup.
"""

import itertools
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import anyio
import pytest
from pydantic import BaseModel
from typing_extensions import override

from inspect_ai import SampleSource, Task, TaskSource, eval_async
from inspect_ai._eval.task.enqueue import TaskStartPolicy, enqueue_task
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
from inspect_ai.util._sandbox.lifecycle import sandbox_lifecycle_state


class FakeConfig(BaseModel, frozen=True):
    name: str


@dataclass
class State:
    """Provider state created by one `task_init` call."""

    label: str  # e.g. "ctxvar_fake:B#2" (provider:config#init-number)
    samples: list[str] = field(default_factory=list)


@dataclass
class Event:
    provider: str
    hook: str  # task_init | sample_init | sample_cleanup | task_cleanup
    config: str
    task: str  # task name passed by Inspect ("startup"/"shutdown" for task hooks)
    state: str  # label of the state the hook saw, or "MISSING"
    samples: tuple[str, ...] = ()  # task_cleanup: sample ids its state holds


EVENTS: list[Event] = []
_init_counter = itertools.count(1)


def _name(config: SandboxEnvironmentConfigType | None) -> str:
    assert isinstance(config, FakeConfig)
    return config.name


class _FakeBase(SandboxEnvironment):
    provider = "base"

    # --- per-pattern state access, overridden below --------------------------
    @classmethod
    def init_state(cls, config: str) -> State:
        raise NotImplementedError

    @classmethod
    def current_state(cls) -> State | None:
        raise NotImplementedError

    # --- lifecycle -----------------------------------------------------------
    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return FakeConfig(**config)

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        state = cls.init_state(_name(config))
        EVENTS.append(
            Event(cls.provider, "task_init", _name(config), task_name, state.label)
        )

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        state = cls.current_state()
        sample_key = f"{task_name}/{metadata.get('n', '?')}"
        if state is not None:
            state.samples.append(sample_key)
        EVENTS.append(
            Event(
                cls.provider,
                "sample_init",
                _name(config),
                sample_key,
                state.label if state else "MISSING",
            )
        )
        return {"default": cls()}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        state = cls.current_state()
        EVENTS.append(
            Event(
                cls.provider,
                "sample_cleanup",
                _name(config),
                task_name,
                state.label if state else "MISSING",
            )
        )

    @override
    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        state = cls.current_state()
        EVENTS.append(
            Event(
                cls.provider,
                "task_cleanup",
                _name(config),
                task_name,
                state.label if state else "MISSING",
                tuple(state.samples) if state else (),
            )
        )

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

    @override
    async def read_file(self, file: str, text: bool = True) -> Any:
        raise NotImplementedError


# Modal / Daytona / E2B / Vector Podman: task_init *sets* fresh state.
_ctxvar_state: ContextVar[State] = ContextVar("ctxvar_fake_state")


@sandboxenv(name="ctxvar_fake")
class CtxVarFake(_FakeBase):
    provider = "ctxvar_fake"

    @override
    @classmethod
    def init_state(cls, config: str) -> State:
        state = State(f"{cls.provider}:{config}#{next(_init_counter)}")
        _ctxvar_state.set(state)
        return state

    @override
    @classmethod
    def current_state(cls) -> State | None:
        return _ctxvar_state.get(None)


# UK AISI k8s (HelmReleaseManager.get_instance): get-or-create.
_goc_state: ContextVar[State] = ContextVar("getorcreate_fake_state")


@sandboxenv(name="getorcreate_fake")
class GetOrCreateFake(_FakeBase):
    provider = "getorcreate_fake"

    @override
    @classmethod
    def init_state(cls, config: str) -> State:
        try:
            return _goc_state.get()
        except LookupError:
            state = State(f"{cls.provider}:{config}#{next(_init_counter)}")
            _goc_state.set(state)
            return state

    @override
    @classmethod
    def current_state(cls) -> State | None:
        return _goc_state.get(None)


# docker / Lizard / inspect_ranges: state on sandbox_lifecycle_state().
@dataclass
class _LifecycleRegistry:
    state: State | None = None


@sandboxenv(name="lifecycle_fake")
class LifecycleFake(_FakeBase):
    provider = "lifecycle_fake"

    @override
    @classmethod
    def init_state(cls, config: str) -> State:
        scope = sandbox_lifecycle_state()
        assert scope is not None
        registry = scope.get(_LifecycleRegistry)
        if registry.state is None:
            registry.state = State(f"{cls.provider}:{config}#{next(_init_counter)}")
        return registry.state

    @override
    @classmethod
    def current_state(cls) -> State | None:
        scope = sandbox_lifecycle_state()
        return scope.get(_LifecycleRegistry).state if scope is not None else None


PROVIDERS = ["ctxvar_fake", "getorcreate_fake", "lifecycle_fake"]


# --- task building -----------------------------------------------------------


@solver
def noop() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def fake_task(
    name: str,
    provider: str,
    config: str,
    solver: Solver | None = None,
    samples: int = 1,
) -> Task:
    return Task(
        name=name,
        dataset=[
            Sample(input="hi", target="ok", id=i, metadata={"n": str(i)})
            for i in range(1, samples + 1)
        ],
        solver=solver or noop(),
        sandbox=SandboxEnvironmentSpec(provider, FakeConfig(name=config)),
    )


def _enqueue(tasks: list[Task], start: TaskStartPolicy | None) -> None:
    enqueue_task(tasks, start=start)


async def _wait_for_sample_init(task: str) -> None:
    with anyio.fail_after(30):
        while not any(
            e.hook == "sample_init" and e.task.startswith(f"{task}/") for e in EVENTS
        ):
            await anyio.sleep(0.01)


@solver
def add_children(provider: str, start: TaskStartPolicy | None, wait: bool) -> Solver:
    # Sample 1 adds `child_b` (config B) and `child_a2` (config A, already
    # started) and, if `wait`, holds until `child_b` has a sample running, so the
    # parent's later sample starts after `child_b`'s `task_init`.

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == 1:
            _enqueue(
                [
                    fake_task("child_b", provider, "B"),
                    fake_task("child_a2", provider, "A"),
                ],
                start,
            )
            if wait:
                await _wait_for_sample_init("child_b")
        return state

    return solve


# --- inspection helpers --------------------------------------------------------


def seen(provider: str, hook: str, task_prefix: str = "") -> list[str]:
    return [
        e.state
        for e in EVENTS
        if e.provider == provider and e.hook == hook and e.task.startswith(task_prefix)
    ]


def sample_state(provider: str, sample: str) -> str:
    (state,) = [
        e.state
        for e in EVENTS
        if e.provider == provider and e.hook == "sample_init" and e.task == sample
    ]
    return state


def cleanup_covers(provider: str) -> set[str]:
    """Sample ids reachable from any task_cleanup's state."""
    return {
        s
        for e in EVENTS
        if e.provider == provider and e.hook == "task_cleanup"
        for s in e.samples
    }


def all_samples(provider: str) -> set[str]:
    return {
        e.task for e in EVENTS if e.provider == provider and e.hook == "sample_init"
    }


# whether the test runs with each task starting its sandboxes in its own slot
# (INSPECT_TASK_SETUP_IN_SLOT=1) or with each group started up before dispatch
IN_SLOT = False


@pytest.fixture(autouse=True, params=["group", "slot"])
def _reset_events(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    global IN_SLOT
    IN_SLOT = request.param == "slot"
    if IN_SLOT:
        monkeypatch.setenv("INSPECT_TASK_SETUP_IN_SLOT", "1")
    else:
        monkeypatch.delenv("INSPECT_TASK_SETUP_IN_SLOT", raising=False)
    EVENTS.clear()
    monkeypatch.setenv("INSPECT_LOG_DIR", str(tmp_path / "logs"))


def init_of(provider: str, config: str) -> str:
    (state,) = [
        e.state
        for e in EVENTS
        if e.provider == provider and e.hook == "task_init" and e.config == config
    ]
    return state


def _ok(logs: list[EvalLog]) -> None:
    assert all(log.status == "success" for log in logs), [
        (log.eval.task, log.status, log.error) for log in logs
    ]


# --- scenarios -----------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_seed_tasks_two_configs(provider: str) -> None:
    """Two seed tasks, configs A and B, run together."""
    logs = await eval_async(
        [fake_task("seed_a", provider, "A"), fake_task("seed_b", provider, "B")],
        model="mockllm/model",
        max_tasks=2,
    )
    _ok(logs)

    assert "MISSING" not in [e.state for e in EVENTS]
    assert cleanup_covers(provider) == all_samples(provider)
    if provider == "ctxvar_fake" and IN_SLOT:
        # each task starts its own sandboxes and sees its own task_init's state
        assert sample_state(provider, "seed_a/1") == init_of(provider, "A")
        assert sample_state(provider, "seed_b/1") == init_of(provider, "B")
    elif provider == "ctxvar_fake":
        # both seed task_inits run before any task starts, so every task sees
        # the last one's state
        inits = seen(provider, "task_init")
        assert sample_state(provider, "seed_a/1") == inits[-1]
        assert sample_state(provider, "seed_b/1") == inits[-1]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("driver", ["eval", "task_source"])
async def test_added_when_free_overlapping(provider: str, driver: str) -> None:
    # A running parent (config A, 2 samples run one at a time) adds `child_b`
    # (config B) and `child_a2` (config A); the parent's 2nd sample starts after
    # `child_b`'s task_init.
    parent = fake_task(
        "parent", provider, "A", add_children(provider, "when_free", True), 2
    )
    tasks: Any = TaskSource.from_tasks([parent]) if driver == "task_source" else parent
    logs = await eval_async(tasks, model="mockllm/model", max_tasks=3, max_samples=1)
    _ok(logs)

    assert "MISSING" not in [e.state for e in EVENTS]
    assert cleanup_covers(provider) == all_samples(provider)
    if provider == "ctxvar_fake":
        inits = seen(provider, "task_init")
        assert len(inits) == 2  # A (seed), then B (added); A2 reuses started A
        state_a, state_b = inits
        # the added task sees the state its own task_init set
        assert sample_state(provider, "child_b/1") == state_b
        # the running parent keeps its own state, also for the sample that
        # started after child_b's task_init
        assert sample_state(provider, "parent/1") == state_a
        assert sample_state(provider, "parent/2") == state_a
        # child_a2 uses config A, already started: it sees the latest state
        # (B's once B's task_init has run, which in the slot mode depends on
        # which of the two children starts first)
        assert sample_state(provider, "child_a2/1") in (
            [state_a, state_b] if IN_SLOT else [state_b]
        )
        # each config's cleanup sees its own task_init's state
        assert sorted(seen(provider, "task_cleanup")) == sorted([state_a, state_b])
    else:
        # get-or-create and lifecycle state: one shared state for the run
        assert len(set(seen(provider, "sample_init"))) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "driver,start",
    [("eval", "after_batch"), ("eval", None), ("task_source", "after_batch")],
)
async def test_added_after_batch(
    provider: str, driver: str, start: TaskStartPolicy | None
) -> None:
    # The parent (config A) adds `child_b` (B) and `child_a2` (A); they start
    # once the parent has finished.
    parent = fake_task("parent", provider, "A", add_children(provider, start, False))
    tasks: Any = TaskSource.from_tasks([parent]) if driver == "task_source" else parent
    logs = await eval_async(tasks, model="mockllm/model", max_tasks=3)
    _ok(logs)

    assert "MISSING" not in [e.state for e in EVENTS]
    assert cleanup_covers(provider) == all_samples(provider)
    if provider == "ctxvar_fake":
        # one dispatcher: B's task_init sets the ContextVar again before the
        # end-of-run cleanups, which still see their own task_init's state
        inits = seen(provider, "task_init")
        assert len(inits) == 2
        state_a, state_b = inits
        assert sample_state(provider, "parent/1") == state_a
        assert sample_state(provider, "child_a2/1") in (
            [state_a, state_b] if IN_SLOT else [state_b]
        )
        assert sorted(seen(provider, "task_cleanup")) == sorted([state_a, state_b])


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("max_tasks", [1, 2])
@pytest.mark.parametrize("via", ["next_tasks", "sample_complete"])
async def test_task_source_batch(provider: str, max_tasks: int, via: str) -> None:
    # A TaskSource seeds `seed_a` (config A) and then adds `next_b` (config B),
    # from next_tasks() or from sample_complete().
    given = False

    async def next_tasks() -> list[Task] | None:
        nonlocal given
        if via == "next_tasks" and not given:
            given = True
            return [fake_task("next_b", provider, "B")]
        return None

    async def sample_complete(sample: Any, task: Task) -> list[Task] | None:
        nonlocal given
        if via == "sample_complete" and not given:
            given = True
            return [fake_task("next_b", provider, "B")]
        return None

    source = TaskSource.from_tasks(
        [fake_task("seed_a", provider, "A")],
        next_tasks=next_tasks,
        sample_complete=sample_complete,
    )
    logs = await eval_async(source, model="mockllm/model", max_tasks=max_tasks)
    _ok(logs)

    assert "MISSING" not in [e.state for e in EVENTS]
    assert cleanup_covers(provider) == all_samples(provider)
    if provider == "ctxvar_fake":
        inits = seen(provider, "task_init")
        assert len(inits) == 2
        assert sample_state(provider, "seed_a/1") == inits[0]
        assert sample_state(provider, "next_b/1") == inits[1]


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_sample_source_late_task_init(provider: str) -> None:
    # A task whose seed dataset is empty gets its first sample from a
    # SampleSource; its config's task_init then runs late, inside the running
    # task (SandboxManager.start_for_samples), not in the run's context.

    class _Src(SampleSource):
        def __init__(self) -> None:
            self._produced = False

        async def next_samples(self) -> list[Sample] | None:
            if not self._produced:
                self._produced = True
                return [Sample(input="added", target="ok", id=1, metadata={"n": "1"})]
            return None

    logs = await eval_async(
        Task(
            name="sourced",
            dataset=_Src(),
            solver=noop(),
            sandbox=SandboxEnvironmentSpec(provider, FakeConfig(name="S")),
        ),
        model="mockllm/model",
    )
    _ok(logs)
    if provider == "lifecycle_fake":
        assert "MISSING" not in [e.state for e in EVENTS]
    else:
        # the state set by the late task_init does not reach the sample (it
        # runs in a sibling task), but the cleanup sees it
        assert sample_state(provider, "sourced/1") == "MISSING"
        assert seen(provider, "task_cleanup") == seen(provider, "task_init")
        assert cleanup_covers(provider) == set()


# --- what task_cleanup sees besides provider state -----------------------------

_cleanup_saw_screen: list[bool] = []


@sandboxenv(name="screen_probe_fake")
class ScreenProbeFake(CtxVarFake):
    provider = "screen_probe_fake"

    @override
    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        from inspect_ai._display.core.active import _active_task_screen

        _cleanup_saw_screen.append(_active_task_screen.get() is not None)
        await super().task_cleanup(task_name, config, cleanup)


@pytest.mark.parametrize("how", ["when_free", "after_batch", "next_tasks"])
async def test_task_cleanup_sees_only_provider_state(how: str) -> None:
    # a config first started for an added task (while the task display is
    # open) is cleaned up after the display has closed: its cleanup sees the
    # provider's state, not the display that was active during its task_init
    _cleanup_saw_screen.clear()
    child = fake_task("child", "screen_probe_fake", "C")

    @solver
    def add_child() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            _enqueue([child], "after_batch" if how == "after_batch" else "when_free")
            return state

        return solve

    given = False

    async def next_tasks() -> list[Task] | None:
        nonlocal given
        if how == "next_tasks" and not given:
            given = True
            return [child]
        return None

    seed = Task(name="seed", dataset=[Sample(input="hi")], solver=add_child())
    tasks: Any = (
        TaskSource.from_tasks([_plain_seed()], next_tasks=next_tasks)
        if how == "next_tasks"
        else seed
    )
    logs = await eval_async(tasks, model="mockllm/model", max_tasks=2)
    _ok(logs)
    assert _cleanup_saw_screen == [False]
    assert cleanup_covers("screen_probe_fake") == all_samples("screen_probe_fake")


def _plain_seed() -> Task:
    return Task(name="seed", dataset=[Sample(input="hi")], solver=noop())
