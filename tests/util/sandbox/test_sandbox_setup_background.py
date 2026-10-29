"""Background work a provider's task_init starts (default mode).

A provider's ``task_init`` starts a background job (here through the eval's
background task group, as ``run_in_background`` does) and returns. Once a
sample starts, the job runs ``pwd`` and prints an environment variable that
the provider's ``task_init_environment`` returned for the setup. The task file
lives in one directory and the eval runs from another. The setup scope ends
when ``task_init`` returns, so the job's later child process runs in the
eval's working directory without the setup's variables.
"""

import os
import textwrap
from pathlib import Path
from typing import Any

import anyio
import pytest
from typing_extensions import override

from inspect_ai import eval_async
from inspect_ai._util.background import run_in_background
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandboxenv,
    subprocess,
)

RECORDS: dict[str, str] = {}
_go = anyio.Event()
_done = anyio.Event()


async def _job() -> None:
    await _go.wait()
    result = await subprocess(["sh", "-c", 'pwd; echo "${BG_SETUP_VAR:-unset}"'])
    RECORDS["job"] = result.stdout.strip().replace("\n", " ")
    _done.set()


@sandboxenv(name="bg_fake")
class BgFake(SandboxEnvironment):
    @override
    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        return {"BG_SETUP_VAR": "from-setup"}

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        run_in_background(_job)

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        _go.set()
        await _done.wait()
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

    @override
    async def read_file(self, file: str, text: bool = True) -> Any:
        raise NotImplementedError


TASK_FILE = textwrap.dedent(
    """
    from inspect_ai import Task, task
    from inspect_ai.dataset import Sample
    from inspect_ai.util import SandboxEnvironmentSpec


    @task
    def bg():
        return Task(
            dataset=[Sample(input="hi")],
            sandbox=SandboxEnvironmentSpec("bg_fake"),
        )
    """
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    global _go, _done
    RECORDS.clear()
    _go = anyio.Event()
    _done = anyio.Event()
    monkeypatch.delenv("INSPECT_TASK_SETUP_IN_SLOT", raising=False)
    monkeypatch.delenv("BG_SETUP_VAR", raising=False)


async def test_background_job_started_by_task_init_runs_outside_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_dir = (tmp_path / "taskdir").resolve()
    launch_dir = (tmp_path / "launch").resolve()
    task_dir.mkdir()
    launch_dir.mkdir()
    (task_dir / "bg_task.py").write_text(TASK_FILE)
    monkeypatch.chdir(launch_dir)
    logs = await eval_async(
        f"{task_dir / 'bg_task.py'}@bg",
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
    )
    assert logs[0].status == "success", logs[0].error
    assert os.getcwd() == str(launch_dir)
    assert RECORDS["job"] == f"{launch_dir} unset"
