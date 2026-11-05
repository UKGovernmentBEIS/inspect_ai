import os
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from inspect_ai.util import SandboxUserUnsupportedError
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._subprocess import ExecResult


@pytest.mark.parametrize(
    "effective_uid, user, requested_uid, supported",
    [
        (1000, None, None, True),
        (1000, "1000", None, True),
        (1000, "current", 1000, True),
        (0, "root", 0, True),
        (0, "0", None, True),
        (1000, "root", 0, False),
        (1000, "0", None, False),
        (0, "other", 1000, False),
        (1000, "missing", None, False),
        (1000, "", None, False),
    ],
)
async def test_local_exec_requires_current_user(
    monkeypatch: pytest.MonkeyPatch,
    effective_uid: int,
    user: str | None,
    requested_uid: int | None,
    supported: bool,
) -> None:
    if os.name != "posix":
        pytest.skip("requires POSIX user identities")
    import pwd

    def lookup(name: str) -> pwd.struct_passwd:
        assert name == user
        assert not name.isdecimal()
        if requested_uid is None:
            raise KeyError(name)
        return pwd.struct_passwd((name, "", requested_uid, 1000, "", "/tmp", "/bin/sh"))

    monkeypatch.setattr(os, "geteuid", lambda: effective_uid)
    monkeypatch.setattr(pwd, "getpwnam", lookup)
    run = AsyncMock(return_value=ExecResult(True, 0, "", ""))
    monkeypatch.setattr("inspect_ai.util._sandbox.local.subprocess", run)
    sandbox = LocalSandboxEnvironment()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if supported:
                assert (await sandbox.exec(["command"], user=user)).success
                run.assert_awaited_once()
            else:
                with pytest.raises(SandboxUserUnsupportedError, match=repr(user)):
                    await sandbox.exec(["command"], user=user)
                run.assert_not_awaited()
        assert not caught
    finally:
        sandbox.directory.cleanup()


async def test_local_sandbox_scopes_server_dir_per_instance() -> None:
    sandbox_a = LocalSandboxEnvironment()
    sandbox_b = LocalSandboxEnvironment()
    try:
        run = AsyncMock(return_value=ExecResult(True, 0, "", ""))
        with patch("inspect_ai.util._sandbox.local.subprocess", run):
            await sandbox_a.exec([SANDBOX_CLI, "start-server"])
            await sandbox_b.exec([SANDBOX_CLI, "start-server"])

        expected_a = str(Path(sandbox_a.directory.name) / "sandbox-tools")
        expected_b = str(Path(sandbox_b.directory.name) / "sandbox-tools")
        assert run.await_args_list[0].kwargs["env"] == {
            "INSPECT_SANDBOX_TOOLS_DIR": expected_a
        }
        assert run.await_args_list[1].kwargs["env"] == {
            "INSPECT_SANDBOX_TOOLS_DIR": expected_b
        }
        assert expected_a != expected_b
    finally:
        sandbox_a.directory.cleanup()
        sandbox_b.directory.cleanup()


async def test_local_sandbox_server_dir_cannot_be_overridden() -> None:
    sandbox = LocalSandboxEnvironment()
    try:
        run = AsyncMock(return_value=ExecResult(True, 0, "", ""))
        with patch("inspect_ai.util._sandbox.local.subprocess", run):
            await sandbox.exec(
                [SANDBOX_CLI, "start-server"],
                env={"INSPECT_SANDBOX_TOOLS_DIR": "/tmp/shared-sandbox-tools"},
            )

        call = run.await_args
        assert call is not None
        assert call.kwargs["env"] == {
            "INSPECT_SANDBOX_TOOLS_DIR": str(
                Path(sandbox.directory.name) / "sandbox-tools"
            )
        }
    finally:
        sandbox.directory.cleanup()


async def test_local_sandbox_does_not_inject_server_dir_into_user_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INSPECT_SANDBOX_TOOLS_DIR", raising=False)
    sandbox = LocalSandboxEnvironment()
    try:
        result = await sandbox.exec(
            ["sh", "-c", 'printf %s "${INSPECT_SANDBOX_TOOLS_DIR-unset}"']
        )

        assert result.stdout == "unset"
    finally:
        sandbox.directory.cleanup()


async def test_sample_cleanup_stops_server_before_removing_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = LocalSandboxEnvironment()
    directory = Path(sandbox.directory.name)

    async def assert_directory_exists(*, timeout: int) -> None:
        assert directory.exists()

    stop_server = AsyncMock(side_effect=assert_directory_exists)
    monkeypatch.setattr(sandbox, "_stop_sandbox_tools", stop_server, raising=False)

    await LocalSandboxEnvironment.sample_cleanup(
        task_name="test",
        config=None,
        environments={"default": sandbox},
        interrupted=False,
    )

    stop_server.assert_awaited_once_with(
        timeout=LocalSandboxEnvironment._SANDBOX_TOOLS_STOP_TIMEOUT
    )
    assert not directory.exists()


async def test_sample_cleanup_removes_directory_when_server_stop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = LocalSandboxEnvironment()
    directory = Path(sandbox.directory.name)
    stop_server = AsyncMock(side_effect=RuntimeError("shutdown failed"))
    monkeypatch.setattr(sandbox, "_stop_sandbox_tools", stop_server, raising=False)

    with patch("inspect_ai.util._sandbox.local.logger") as logger:
        await LocalSandboxEnvironment.sample_cleanup(
            task_name="test",
            config=None,
            environments={"default": sandbox},
            interrupted=True,
        )

    assert not directory.exists()
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args == (
        "Failed to stop local sandbox-tools server: %s",
        stop_server.side_effect,
    )


async def test_interrupted_sample_cleanup_uses_short_server_stop_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = LocalSandboxEnvironment()
    stop_server = AsyncMock()
    monkeypatch.setattr(sandbox, "_stop_sandbox_tools", stop_server, raising=False)

    await LocalSandboxEnvironment.sample_cleanup(
        task_name="test",
        config=None,
        environments={"default": sandbox},
        interrupted=True,
    )

    stop_server.assert_awaited_once_with(
        timeout=LocalSandboxEnvironment._INTERRUPTED_SANDBOX_TOOLS_STOP_TIMEOUT
    )


async def test_sample_cleanup_without_server_is_idempotent() -> None:
    sandbox = LocalSandboxEnvironment()

    await LocalSandboxEnvironment.sample_cleanup(
        task_name="test",
        config=None,
        environments={"default": sandbox},
        interrupted=False,
    )
    await LocalSandboxEnvironment.sample_cleanup(
        task_name="test",
        config=None,
        environments={"default": sandbox},
        interrupted=True,
    )


async def test_sample_cleanup_ignores_unrelated_sandbox_tools_directory() -> None:
    sandbox = LocalSandboxEnvironment()
    Path(sandbox.directory.name, "sandbox-tools").mkdir()
    run = AsyncMock(return_value=ExecResult(True, 0, "", ""))

    with patch("inspect_ai.util._sandbox.local.subprocess", run):
        await LocalSandboxEnvironment.sample_cleanup(
            task_name="test",
            config=None,
            environments={"default": sandbox},
            interrupted=False,
        )

    run.assert_not_awaited()


async def test_sample_cleanup_continues_after_server_stop_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = LocalSandboxEnvironment()
    succeeding = LocalSandboxEnvironment()
    failing_directory = Path(failing.directory.name)
    succeeding_directory = Path(succeeding.directory.name)
    failing_stop = AsyncMock(side_effect=RuntimeError("shutdown failed"))
    succeeding_stop = AsyncMock()
    monkeypatch.setattr(failing, "_stop_sandbox_tools", failing_stop)
    monkeypatch.setattr(succeeding, "_stop_sandbox_tools", succeeding_stop)

    with patch("inspect_ai.util._sandbox.local.logger") as logger:
        await LocalSandboxEnvironment.sample_cleanup(
            task_name="test",
            config=None,
            environments={"failing": failing, "succeeding": succeeding},
            interrupted=True,
        )

    failing_stop.assert_awaited_once_with(
        timeout=LocalSandboxEnvironment._INTERRUPTED_SANDBOX_TOOLS_STOP_TIMEOUT
    )
    succeeding_stop.assert_awaited_once_with(
        timeout=LocalSandboxEnvironment._INTERRUPTED_SANDBOX_TOOLS_STOP_TIMEOUT
    )
    assert not failing_directory.exists()
    assert not succeeding_directory.exists()
    logger.warning.assert_called_once()
    assert logger.warning.call_args.args == (
        "Failed to stop local sandbox-tools server: %s",
        failing_stop.side_effect,
    )
