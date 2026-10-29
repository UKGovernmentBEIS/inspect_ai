"""How a sandbox provider's task_init and task_cleanup run (default mode).

Each ``task_init`` and ``task_cleanup`` runs in a child task, and only the
ContextVars a ``task_init`` sets are recorded for its config. A fake provider
records what each hook sees. All tests run with INSPECT_TASK_SETUP_IN_SLOT
unset.
"""

from contextvars import ContextVar
from pathlib import Path
from typing import Any

import anyio
import pytest
import sniffio
from pydantic import BaseModel
from typing_extensions import override

from inspect_ai import Task, eval_async
from inspect_ai._eval.task.enqueue import enqueue_task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    sandboxenv,
)


class Cfg(BaseModel, frozen=True):
    name: str
    mode: str = "plain"


_V: ContextVar[str] = ContextVar("hooks_v")
_W: ContextVar[str] = ContextVar("hooks_w")
RECORDS: list[tuple[str, str, str, str]] = []
_swallow_started = anyio.Event()


def _cfg(config: SandboxEnvironmentConfigType | None) -> Cfg:
    assert isinstance(config, Cfg)
    return config


@sandboxenv(name="hooks_fake")
class HooksFake(SandboxEnvironment):
    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return Cfg(**config)

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        cfg = _cfg(config)
        RECORDS.append(("task_init", cfg.name, _V.get("unset"), _W.get("unset")))
        if cfg.mode == "sysexit":
            raise SystemExit(3)
        if cfg.mode == "swallow":
            _swallow_started.set()
            try:
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                RECORDS.append(("swallowed", cfg.name, "", ""))
        if cfg.mode == "group":
            raise ExceptionGroup("two failures", [ValueError("x"), KeyError("y")])
        _V.set(f"V-{cfg.name}")
        if cfg.name == "B":
            _W.set("W-B")

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        RECORDS.append(
            ("sample_init", _cfg(config).name, _V.get("unset"), _W.get("unset"))
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
        pass

    @override
    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        RECORDS.append(
            ("task_cleanup", _cfg(config).name, _V.get("unset"), _W.get("unset"))
        )
        if _cfg(config).mode == "cleanup_kbd":
            raise KeyboardInterrupt()

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


@solver
def adds(added: list[Task]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if added:
            enqueue_task(added.pop(), start="when_free")
        return state

    return solve


def _task(name: str, mode: str = "plain", added: Task | None = None) -> Task:
    return Task(
        name=f"t{name}",
        dataset=[Sample(input="hi")],
        solver=adds([added] if added is not None else []),
        sandbox=SandboxEnvironmentSpec("hooks_fake", Cfg(name=name, mode=mode)),
    )


@pytest.fixture(autouse=True)
def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global _swallow_started
    RECORDS.clear()
    _swallow_started = anyio.Event()
    monkeypatch.setenv("INSPECT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("INSPECT_TASK_SETUP_IN_SLOT", raising=False)


def _describe(ex: BaseException) -> str:
    if isinstance(ex, BaseExceptionGroup):
        inner = ", ".join(_describe(e) for e in ex.exceptions)
        return f"{type(ex).__name__}[{inner}]"
    return repr(ex)


@pytest.mark.parametrize("mode", ["sysexit", "group"])
@pytest.mark.parametrize("where", ["seed", "added"])
async def test_task_init_base_exception(tmp_path: Path, mode: str, where: str) -> None:
    if (where, mode) == (
        "seed",
        "sysexit",
    ) and sniffio.current_async_library() == "asyncio":
        pytest.skip("SystemExit escapes the asyncio event loop")
    if where == "seed":
        # one task: the order configs of a group start in is set order
        tasks = [_task("F", mode)]
    else:
        tasks = [_task("A", added=_task("F", mode))]
    raised = "nothing"
    try:
        await eval_async(tasks, model="mockllm/model")
    except BaseException as ex:
        raised = _describe(ex)
    cleanups = sorted(r[1] for r in RECORDS if r[0] == "task_cleanup")
    # an exception group is reduced to one of its exceptions, chosen at random
    expected_raised = {
        ("sysexit", "seed"): {"BaseExceptionGroup[SystemExit(3)]"},
        ("sysexit", "added"): {"BaseExceptionGroup[BaseExceptionGroup[SystemExit(3)]]"},
        ("group", "seed"): {"ValueError('x')", "KeyError('y')"},
        ("group", "added"): {"ValueError('x')", "KeyError('y')"},
    }[(mode, where)]
    assert raised in expected_raised
    assert cleanups == (["A"] if where == "added" else [])


async def test_cleanup_sees_only_its_own_init_state() -> None:
    """Seed tA (config A) adds tB (config B); both succeed.

    task_init(A) sets V; task_init(B) sets V and W. task_cleanup(A)
    sees V="V-A" and W unset (W is a later task_init's
    value), and task_cleanup(B) V="V-B", W="W-B".
    """
    logs = await eval_async([_task("A", added=_task("B"))], model="mockllm/model")
    assert [log.status for log in logs] == ["success", "success"]
    cleanups = sorted(r for r in RECORDS if r[0] == "task_cleanup")
    assert cleanups == [
        ("task_cleanup", "A", "V-A", "unset"),
        ("task_cleanup", "B", "V-B", "W-B"),
    ]


async def test_added_task_init_swallowing_run_cancel(tmp_path: Path) -> None:
    """The run is cancelled while an added task's task_init runs; it swallows it.

    tA (config A) adds tS (config S) when_free; tS's task_init catches the
    cancellation and returns. The run's cancellation propagates, both
    cleanups run and only tA's cancelled log is on disk.
    """
    from inspect_ai.log import read_eval_log_async

    outcome = "returned"
    with anyio.CancelScope() as outer:

        async def cancel_when_started() -> None:
            await _swallow_started.wait()
            outer.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(cancel_when_started)
            try:
                logs = await eval_async(
                    [_task("A", added=_task("S", "swallow"))], model="mockllm/model"
                )
                outcome = "returned " + ",".join(log.status for log in logs)
            except anyio.get_cancelled_exc_class():
                outcome = "cancelled"
                raise
            finally:
                tg.cancel_scope.cancel()
    disk = sorted(
        (log.eval.task, log.status)
        for log in [
            await read_eval_log_async(str(path), header_only=True)
            for path in (tmp_path / "logs").glob("*.eval")
        ]
    )
    result = (outcome, sorted(r[:2] for r in RECORDS if r[0] != "sample_init"), disk)
    assert result == (
        "cancelled",
        [
            ("swallowed", "S"),
            ("task_cleanup", "A"),
            ("task_cleanup", "S"),
            ("task_init", "A"),
            ("task_init", "S"),
        ],
        [("tA", "cancelled")],
    )


async def test_task_cleanup_raising_keyboard_interrupt() -> None:
    """A task_cleanup raising KeyboardInterrupt: logged, the other cleanup runs."""
    logs = await eval_async(
        [_task("A", "cleanup_kbd"), _task("B")], model="mockllm/model"
    )
    assert [log.status for log in logs] == ["success", "success"]
    assert sorted(r[1] for r in RECORDS if r[0] == "task_cleanup") == ["A", "B"]
