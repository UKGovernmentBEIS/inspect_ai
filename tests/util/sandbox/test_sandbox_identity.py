"""The sandbox identity scope: resolution, default sandbox and injection target."""

from collections.abc import Iterator
from contextlib import contextmanager

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.util import (
    SandboxEnvironment,
    SandboxIdentityError,
    sandbox,
    sandbox_default,
    sandbox_identity,
    sandbox_identity_active,
    sandbox_identity_cwd,
    sandbox_identity_user,
)
from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_default_context_var,
    sandbox_environments_context_var,
    sandbox_with_injection,
)
from inspect_ai.util._subprocess import ExecResult

OK = ExecResult(True, 0, "", "")


@contextmanager
def _environments(**environments: SandboxEnvironment) -> Iterator[None]:
    envs_token = sandbox_environments_context_var.set(environments)
    default_token = sandbox_default_context_var.set(next(iter(environments)))
    try:
        yield
    finally:
        sandbox_default_context_var.reset(default_token)
        sandbox_environments_context_var.reset(envs_token)


@pytest.fixture
def default() -> CannedSandbox:
    return CannedSandbox.returning(OK)


@pytest.fixture
def workspace() -> CannedSandbox:
    return CannedSandbox.returning(OK)


def test_outside_a_scope_resolution_returns_its_argument(
    default: CannedSandbox,
) -> None:
    with _environments(default=default):
        assert sandbox_identity_user(default, None, strict=True) is None
        assert sandbox_identity_user(default, "root", strict=True) == "root"
        assert sandbox_identity_cwd(default, None) is None
        assert sandbox_identity_cwd(default, "/x") == "/x"
        assert not sandbox_identity_active()
        assert not sandbox_identity_active(default)


def test_inside_a_scope_resolves_to_the_scope(default: CannedSandbox) -> None:
    with _environments(default=default), sandbox_identity("w-1", cwd="/home/w-1"):
        assert sandbox_identity_user(default, None, strict=True) == "w-1"
        assert sandbox_identity_user(default, "w-1", strict=True) == "w-1"
        assert sandbox_identity_user(default, "root", strict=False) == "root"
        with pytest.raises(SandboxIdentityError, match="'root'.*'w-1'"):
            sandbox_identity_user(default, "root", strict=True)
        assert sandbox_identity_cwd(default, None) == "/home/w-1"
        assert sandbox_identity_cwd(default, "/x") == "/x"
        assert sandbox_identity_active()
        assert sandbox_identity_active(default)
    assert not sandbox_identity_active()


def test_scope_for_another_sandbox_leaves_resolution_alone(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    with (
        _environments(default=default, workspace=workspace),
        sandbox_identity("w-1", cwd="/home/w-1", sandbox="workspace"),
    ):
        assert sandbox_identity_user(default, "root", strict=True) == "root"
        assert sandbox_identity_user(default, None, strict=True) is None
        assert sandbox_identity_cwd(default, None) is None
        assert sandbox_identity_active()
        assert not sandbox_identity_active(default)
        assert sandbox_identity_active(workspace)


def test_nested_scopes_raise(default: CannedSandbox) -> None:
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(SandboxIdentityError, match="cannot be nested"):
            with sandbox_identity("w-1"):
                pass


def test_unknown_sandbox_raises(default: CannedSandbox) -> None:
    with _environments(default=default):
        with pytest.raises(ValueError, match="'workspace' is not a recognized"):
            with sandbox_identity("w-1", sandbox="workspace"):
                pass
        assert not sandbox_identity_active()


def test_empty_user_raises(default: CannedSandbox) -> None:
    with _environments(default=default):
        with pytest.raises(ValueError, match="requires a user"):
            with sandbox_identity(""):
                pass


def test_no_sandbox_raises() -> None:
    with pytest.raises(ProcessLookupError):
        with sandbox_identity("w-1"):
            pass


def test_scope_sandbox_is_the_default_inside_the_block(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    with _environments(default=default, workspace=workspace):
        with sandbox_identity("w-1", sandbox="workspace"):
            assert sandbox() is workspace
            assert sandbox("default") is workspace
        assert sandbox() is default


def test_default_names_the_current_default(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    with (
        _environments(default=default, workspace=workspace),
        sandbox_default("workspace"),
        sandbox_identity("w-1"),
    ):
        assert sandbox_identity_active(workspace)
        assert sandbox() is workspace


async def test_tasks_started_inside_inherit_the_scope(
    default: CannedSandbox,
) -> None:
    users: list[str | None] = []

    async def resolve() -> None:
        users.append(sandbox_identity_user(default, None, strict=True))

    with _environments(default=default):
        with sandbox_identity("w-1"):
            async with anyio.create_task_group() as tg:
                tg.start_soon(resolve)
        async with anyio.create_task_group() as tg:
            tg.start_soon(resolve)
    assert users == ["w-1", None]


async def test_exec_is_unchanged_inside_a_scope(default: CannedSandbox) -> None:
    # scorers and other trusted code calling exec() keep the default user
    with _environments(default=default), sandbox_identity("w-1"):
        await sandbox().exec(["true"])
    assert default.exec_calls == [(["true"], None)]


def _injectable(installed: set[SandboxEnvironment]) -> SandboxInjectable:
    async def detector(env: SandboxEnvironment) -> bool:
        return env in installed

    async def injector(env: SandboxEnvironment) -> None:
        installed.add(env)

    return SandboxInjectable(detector, injector)


async def test_injection_targets_the_scope_sandbox(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    installed: set[SandboxEnvironment] = {default}
    with _environments(default=default, workspace=workspace):
        # outside a scope the sandbox that needs no injection wins
        assert await sandbox_with_injection(_injectable(installed)) is default
        with sandbox_identity("w-1", sandbox="workspace"):
            assert await sandbox_with_injection(_injectable(installed)) is workspace
            assert workspace in installed


async def test_injection_by_name_ignores_the_scope(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    installed: set[SandboxEnvironment] = set()
    with _environments(default=default, workspace=workspace), sandbox_identity("w-1"):
        assert (
            await sandbox_with_injection(_injectable(installed), name="workspace")
            is workspace
        )
        assert installed == {workspace}
