import inspect
import os
from pathlib import Path
from typing import Literal, overload
from unittest.mock import AsyncMock

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai._eval.task.sandbox import read_sandboxenv_file, resolve_sample_files
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import MemoryDataset
from inspect_ai.event import SandboxEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.solver._solver import Solver, solver
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._sandbox.environment import SandboxUserUnsupportedError
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment

FILES_DIR = Path(__file__).parent / "test_sandbox_files"


async def test_file_user_events_roundtrip() -> None:
    if os.name != "posix":
        pytest.skip("requires POSIX user identities")
    provider = LocalSandboxEnvironment()
    proxy = SandboxEnvironmentProxy(provider)
    user = str(os.geteuid())
    try:
        await proxy.write_file("file", b"\xff\r\n", user=user)
        assert await proxy.read_file("file", False, user=user) == b"\xff\r\n"
        events = transcript().events[-2:]
        assert [
            event.action for event in events if isinstance(event, SandboxEvent)
        ] == ["write_file", "read_file"]
        for event in events:
            assert isinstance(event, SandboxEvent)
            restored = SandboxEvent.model_validate_json(event.model_dump_json())
            assert restored.options == {"user": user}
        legacy = SandboxEvent.model_validate(
            {"event": "sandbox", "action": "read_file", "file": "old"}
        )
        assert legacy.options is None
    finally:
        provider.directory.cleanup()


class _LegacyFileSandbox(LocalSandboxEnvironment):
    async def write_file(
        self, file: str, contents: str | bytes, **kwargs: object
    ) -> None:
        await super().write_file(file, contents)

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, **kwargs: object
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], **kwargs: object
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, **kwargs: object
    ) -> str | bytes:
        if text:
            return await super().read_file(file)
        return await super().read_file(file, False)


@pytest.mark.parametrize("operation", ["read_file", "write_file"])
async def test_old_file_provider_rejects_explicit_user_before_call(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _LegacyFileSandbox()
    proxy = SandboxEnvironmentProxy(SandboxEnvironmentProxy(provider))
    called = AsyncMock(wraps=getattr(provider, operation))
    # Keep the legacy signature visible while recording any invocation.
    called.__signature__ = inspect.signature(getattr(provider, operation))
    monkeypatch.setattr(provider, operation, called)
    try:
        with pytest.raises(SandboxUserUnsupportedError, match="does not support"):
            if operation == "read_file":
                await proxy.read_file("secret", user="agent")
            else:
                await proxy.write_file("secret", "changed", user="agent")
        called.assert_not_awaited()
        with proxy.no_events():
            await proxy.write_file("old", b"legacy")
            assert await proxy.read_file("old", False) == b"legacy"
    finally:
        provider.directory.cleanup()


@pytest.mark.parametrize("operation", ["read_file", "write_file"])
@pytest.mark.parametrize(
    "failure", [PermissionError, TimeoutError, TypeError, SandboxUserUnsupportedError]
)
async def test_file_user_failure_never_retries_without_user(
    operation: str, failure: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = LocalSandboxEnvironment()
    calls: list[str | None] = []

    async def fail(*args: object, user: str | None = None) -> None:
        calls.append(user)
        raise failure("requested user failed")

    monkeypatch.setattr(provider, operation, fail)
    proxy = SandboxEnvironmentProxy(provider)
    try:
        with pytest.raises(failure, match="requested user failed"):
            if operation == "read_file":
                await proxy.read_file("secret", user="agent")
            else:
                await proxy.write_file("secret", "changed", user="agent")
        assert calls == ["agent"]
    finally:
        provider.directory.cleanup()


def test_resolve_sample_files_empty_string_is_literal_content() -> None:
    # "" must be treated as empty file contents, not as a path (fsspec
    # resolves "" to the cwd, which would copy the entire working
    # directory into the sandbox)
    files = {"submission/report.md": ""}
    assert resolve_sample_files(files) == files


async def test_read_sandboxenv_file_empty_string_is_literal_content() -> None:
    assert await read_sandboxenv_file("") == b""


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_files_dir() -> None:
    def check_sandbox_files_dir(files_dir: Path) -> None:
        files = {files_dir.name: files_dir.as_posix()}
        dataset = MemoryDataset([Sample(input="Here are some files", files=files)])

        task = Task(
            dataset=dataset,
            solver=[verify_files(files_dir)],
            sandbox="docker",
        )

        log = eval(task, model="mockllm/model")[0]
        assert log.status == "success"

    check_sandbox_files_dir(FILES_DIR / "dir1")
    check_sandbox_files_dir(FILES_DIR / "dir1" / "dirA")


@solver
def verify_files(files_dir: Path) -> Solver:
    # list of relative file paths
    relative_paths = [
        f"{files_dir.name}/{str(path.relative_to(files_dir))}"
        for path in files_dir.rglob("*")
        if path.is_file()
    ]

    async def solve(state, generate):
        for path in relative_paths:
            try:
                await sandbox().read_file(path)
            except FileNotFoundError:
                assert False

        return state

    return solve
