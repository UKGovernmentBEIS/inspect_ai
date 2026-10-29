"""A sandbox provider call that raises ``asyncio.CancelledError`` itself.

For example a ``task_init`` awaiting a shared background task that someone else
cancelled, while the run itself is not cancelled. The error must reach Inspect
as any failure of ``task_init`` or ``task_cleanup`` does. asyncio only: trio's
``Cancelled`` can't be raised by user code.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_trio
from typing_extensions import override

from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    sandboxenv,
)

EVENTS: list[str] = []


async def _cancelled_background_task() -> None:
    """Await a background task the provider shares, cancelled by someone else."""
    pull = asyncio.ensure_future(asyncio.Event().wait())
    pull.cancel()
    await pull


class Cfg(BaseModel, frozen=True):
    name: str


@sandboxenv(name="r4a_cancelled_fake")
class CancelledFake(SandboxEnvironment):
    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return Cfg(**config)

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        EVENTS.append("task_init")
        assert isinstance(config, Cfg)
        if config.name == "init":
            await _cancelled_background_task()

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        EVENTS.append("sample_init")
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
        EVENTS.append("task_cleanup")
        assert isinstance(config, Cfg)
        if config.name == "cleanup":
            await _cancelled_background_task()

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


@pytest.fixture(autouse=True)
def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    EVENTS.clear()
    monkeypatch.setenv("INSPECT_LOG_DIR", str(tmp_path / "logs"))


@skip_if_trio
async def test_task_init_raising_cancelled_error_does_not_run_the_task() -> None:
    task = Task(
        name="t",
        dataset=[Sample(input="hi")],
        sandbox=SandboxEnvironmentSpec("r4a_cancelled_fake", Cfg(name="init")),
    )
    outcome: str
    try:
        logs = await eval_async(task, model="mockllm/model")
        outcome = ",".join(log.status for log in logs)
    except BaseException as ex:
        outcome = type(ex).__name__
    print("OUTCOME", outcome, EVENTS)
    # the failed task_init ends the run before the task starts
    # (eval_async then raises AssertionError "Eval async did not return a
    # result."); the candidate's child task swallows the CancelledError, so
    # the setup looks successful, the task runs, and no task_cleanup runs
    assert EVENTS == ["task_init"]
    assert outcome != "success"


@skip_if_trio
async def test_task_cleanup_raising_cancelled_error_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    task = Task(
        name="t",
        dataset=[Sample(input="hi")],
        sandbox=SandboxEnvironmentSpec("r4a_cancelled_fake", Cfg(name="cleanup")),
    )
    logs = await eval_async(task, model="mockllm/model")
    assert [log.status for log in logs] == ["success"]
    assert EVENTS == ["task_init", "sample_init", "task_cleanup"]
    # the failed cleanup is logged, as for any other error it raises
    assert any(
        "Error occurred shutting down sandbox environments" in r.getMessage()
        for r in caplog.records
    )
