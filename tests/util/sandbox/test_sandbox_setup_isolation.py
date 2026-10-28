"""Sandbox setup without process-wide working directory or environment changes.

A provider's ``task_init_environment``, ``task_init`` and ``task_cleanup`` run
with the process's own working directory and environment, which every running
task shares. The task's directory and its setup env vars are available through
``sandbox_setup()`` and are applied by ``subprocess()`` to child processes.
Relative config files named by samples built in Python resolve against the
task's directory in every hook, as task-level configs do. These tests load a
task file from one directory while the process runs in another.
"""

import os
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from typing_extensions import override

from inspect_ai import eval
from inspect_ai.util import (
    ComposeConfig,
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    sandbox_setup,
    sandboxenv,
    subprocess,
)

RECORDS: list[dict[str, Any]] = []


def _describe(config: SandboxEnvironmentConfigType | None) -> dict[str, Any]:
    setup = sandbox_setup()
    described: dict[str, Any] = {
        "cwd": os.getcwd(),
        "setup_dir": setup.task_dir if setup else None,
        "environ": os.environ.get("SETUP_ISOLATION_VAR"),
    }
    if isinstance(config, str):
        described |= {"config": config, "exists": Path(config).exists()}
    return described


@sandboxenv(name="setup_isolation_fake")
class SetupIsolationFake(SandboxEnvironment):
    @override
    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return ComposeConfig(**config)

    @override
    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        RECORDS.append({"hook": "task_init_environment", **_describe(config)})
        return {"SETUP_ISOLATION_VAR": "from-task-init-environment"}

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        pwd = await subprocess(["pwd"])
        var = await subprocess(["sh", "-c", "echo $SETUP_ISOLATION_VAR"])
        RECORDS.append(
            {
                "hook": "task_init",
                "child_cwd": pwd.stdout.strip(),
                "child_var": var.stdout.strip(),
                **_describe(config),
            }
        )

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        RECORDS.append({"hook": "sample_init", **_describe(config)})
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
        RECORDS.append({"hook": "task_cleanup", **_describe(config)})

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
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util import ComposeConfig, SandboxEnvironmentSpec


    @solver
    def noop():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return state

        return solve


    @task
    def sample_level_string():
        # relative string config placed on a Sample in Python code
        return Task(
            dataset=[
                Sample(
                    input="hi",
                    sandbox=SandboxEnvironmentSpec("setup_isolation_fake", "compose.yaml"),
                )
            ],
            solver=noop(),
        )


    @task
    def sample_level_compose_config():
        # a ComposeConfig object (providers resolve its build contexts
        # against Path.cwd())
        return Task(
            dataset=[
                Sample(
                    input="hi",
                    sandbox=SandboxEnvironmentSpec(
                        "setup_isolation_fake",
                        ComposeConfig.model_validate(
                            {"services": {"default": {"build": {"context": "img"}}}}
                        ),
                    ),
                )
            ],
            solver=noop(),
        )


    @task
    def task_level_string():
        # the same relative string, at task level (the loader makes it absolute)
        return Task(
            dataset=[Sample(input="hi")],
            solver=noop(),
            sandbox=SandboxEnvironmentSpec("setup_isolation_fake", "compose.yaml"),
        )
    """
)


@pytest.mark.parametrize(
    "task_name",
    ["sample_level_string", "sample_level_compose_config", "task_level_string"],
)
def test_setup_runs_without_process_wide_changes(
    task_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    RECORDS.clear()
    task_dir = (tmp_path / "taskdir").resolve()
    launch_dir = (tmp_path / "launch").resolve()
    task_dir.mkdir()
    launch_dir.mkdir()
    (task_dir / "relcfg_task.py").write_text(TASK_FILE)
    (task_dir / "compose.yaml").write_text("services: {}\n")
    monkeypatch.chdir(launch_dir)

    logs = eval(
        f"{task_dir / 'relcfg_task.py'}@{task_name}",
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path / "logs"),
    )
    assert logs[0].status == "success", logs[0].error

    by_hook = {r["hook"]: r for r in RECORDS}
    assert set(by_hook) == {
        "task_init_environment",
        "task_init",
        "sample_init",
        "task_cleanup",
    }
    for record in RECORDS:
        # the process's working directory and environment never change
        assert record["cwd"] == str(launch_dir)
        assert record["environ"] is None
        # the task's directory is available during setup and cleanup only
        expected_dir = None if record["hook"] == "sample_init" else str(task_dir)
        assert record["setup_dir"] == expected_dir
    # child processes started by subprocess() during setup run in the task's
    # directory, with the setup env vars
    assert by_hook["task_init"]["child_cwd"] == str(task_dir)
    assert by_hook["task_init"]["child_var"] == "from-task-init-environment"
    if task_name != "sample_level_compose_config":
        # a relative config names the task-directory file in every hook
        for hook in ("task_init", "sample_init", "task_cleanup"):
            assert by_hook[hook]["config"] == str(task_dir / "compose.yaml")
            assert by_hook[hook]["exists"] is True
