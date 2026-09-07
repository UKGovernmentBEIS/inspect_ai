"""Tests for the verified framework-directory helper.

The helper's verification is a POSIX ``sh`` script run inside the sandbox, so most
tests here run it for real through ``LocalSandboxEnvironment`` against a temporary
parent directory on the host (Linux only, via the ``local`` fixture: the script
relies on ``stat -c``). Tests that need another uid, a missing tool, or a lost
``mkdir`` race arrange it with a ``PATH`` shim. The remaining tests run anywhere:
path splitting, script syntax, and a scripted fake sandbox covering the Python-side
classification of results a provider might return.
"""

import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Iterator, Literal, overload

import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.util._sandbox._framework_directory import (
    _CREATE_FAILED_MARKER,
    _MISSING_MARKER,
    _SCRIPT,
    _SHELL,
    _UNAVAILABLE_MARKER,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
    FrameworkDirectoryNotFoundError,
    FrameworkDirectoryUnavailableError,
    FrameworkDirectoryUserError,
    FrameworkPath,
    ensure_framework_directory,
    exec_in_framework_directory,
    split_framework_path,
    verify_framework_directory,
)
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._subprocess import ExecResult


@pytest.fixture
def parent(tmp_path: Path) -> Path:
    """A parent directory owned by the test user and not writable by others."""
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    return parent


@pytest.fixture
def local() -> Iterator[LocalSandboxEnvironment]:
    """A real local sandbox for running the verification script (Linux only)."""
    if sys.platform != "linux":
        pytest.skip("verification script requires GNU/BusyBox stat")
    sandbox = LocalSandboxEnvironment()
    yield sandbox
    sandbox.directory.cleanup()


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


class _EnvSandbox(SandboxEnvironment):
    """Runs commands via another sandbox with extra environment variables."""

    def __init__(self, inner: SandboxEnvironment, env: dict[str, str]) -> None:
        super().__init__()
        self.inner = inner
        self.env = env

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
        return await self.inner.exec(cmd, input, cwd, {**(env or {}), **self.env})

    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise NotImplementedError

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


def _tool_dir(tmp_path: Path, tools: list[str], shims: dict[str, str]) -> Path:
    """Build a bin dir with symlinks to real ``tools`` and scripted ``shims``."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in tools:
        found = shutil.which(tool)
        assert found, f"{tool} not found on host"
        os.symlink(found, bindir / tool)
    for name, body in shims.items():
        (bindir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bindir / name).chmod(0o700)
    return bindir


_SCRIPT_PATH_LINE = "PATH=/usr/sbin:/usr/bin:/sbin:/bin"


def _script_with_path(bindir: Path) -> str:
    """The verification script with its PATH pinned to ``bindir`` only.

    The real script uses the system directories and nothing else, so a tool can
    only be shimmed (or hidden) by replacing that line for the test.
    """
    assert _SCRIPT_PATH_LINE in _SCRIPT
    return _SCRIPT.replace(_SCRIPT_PATH_LINE, f"PATH={bindir}")


class _ScriptOverrideSandbox(_EnvSandbox):
    """Substitutes a variant of the verification script (for PATH shims)."""

    def __init__(self, inner: SandboxEnvironment, script: str) -> None:
        super().__init__(inner, {})
        self.script = script

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
        assert cmd[:3] == [_SHELL, "-c", _SCRIPT]
        return await self.inner.exec([_SHELL, "-c", self.script, *cmd[3:]], input, cwd)


async def test_creates_missing_directory_with_mode_0700(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    assert target.is_dir() and not target.is_symlink()
    assert _mode(target) == 0o700


async def test_creates_missing_parent_chain(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    """Auto-created parents get the conventional 0755, not the leaf's 0700."""
    target = parent / "a" / "b" / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    assert _mode(target) == 0o700
    assert _mode(parent / "a") == 0o755
    assert _mode(parent / "a" / "b") == 0o755


async def test_creates_directory_whose_name_starts_with_a_dash(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "-dashed"
    await ensure_framework_directory(local, str(target), user=None)
    assert target.is_dir() and _mode(target) == 0o700


async def test_adopts_existing_conforming_directory(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    target.mkdir(mode=0o700)
    (target / "keep").write_text("x")
    await ensure_framework_directory(local, str(target), user=None)
    await verify_framework_directory(local, str(target), user=None)
    assert (target / "keep").read_text() == "x"


async def test_creates_in_setgid_parent_and_clears_inherited_bits(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    parent.chmod(0o2700)
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    assert _mode(target) == 0o700


def _chmod_after_mkdir(mode: int) -> Callable[[Path], None]:
    def arrange(target: Path) -> None:
        target.mkdir()
        target.chmod(mode)

    return arrange


@pytest.mark.parametrize(
    "arrange, expected_fragment",
    [
        pytest.param(
            lambda t: os.symlink(t.parent, t),
            "is a symbolic link",
            id="symlink-to-directory",
        ),
        pytest.param(
            lambda t: os.symlink(t.parent / "missing", t),
            "is a symbolic link",
            id="dangling-symlink",
        ),
        pytest.param(
            lambda t: t.write_text(""),
            "is not a directory",
            id="regular-file",
        ),
        pytest.param(
            _chmod_after_mkdir(0o755),
            "has mode 755, expected 700",
            id="group-other-readable",
        ),
        pytest.param(
            _chmod_after_mkdir(0o770),
            "has mode 770, expected 700",
            id="group-writable",
        ),
        pytest.param(
            _chmod_after_mkdir(0o2700),
            "has mode 2700, expected 700",
            id="pre-existing-setgid",
        ),
    ],
)
async def test_rejects_nonconforming_entry_and_leaves_it_alone(
    local: LocalSandboxEnvironment,
    parent: Path,
    arrange: Callable[[Path], object],
    expected_fragment: str,
) -> None:
    target = parent / "fw"
    arrange(target)
    before = os.lstat(target)

    with pytest.raises(FrameworkDirectoryError, match=expected_fragment) as excinfo:
        await ensure_framework_directory(local, str(target), user=None)
    assert not isinstance(excinfo.value, FrameworkDirectoryNotFoundError)

    after = os.lstat(target)
    assert (after.st_ino, after.st_mode) == (before.st_ino, before.st_mode)


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o2700, 0o4755, 0o1700], ids=oct)
async def test_repair_mode_tightens_owned_directory_and_keeps_contents(
    local: LocalSandboxEnvironment, parent: Path, mode: int
) -> None:
    """The shape an older rootless install left behind is reused, not refused."""
    target = parent / "fw"
    target.mkdir()
    target.chmod(mode)
    (target / "keep").write_text("x")
    before = os.lstat(target)

    await ensure_framework_directory(local, str(target), user=None, repair_mode=True)

    assert _mode(target) == 0o700
    assert os.lstat(target).st_ino == before.st_ino
    assert (target / "keep").read_text() == "x"
    # Once repaired, the plain (non-repairing) checks accept it.
    await verify_framework_directory(local, str(target), user=None)


@pytest.mark.parametrize(
    "arrange, expected_fragment",
    [
        pytest.param(
            lambda t: os.symlink(t.parent, t), "is a symbolic link", id="symlink"
        ),
        pytest.param(lambda t: t.write_text(""), "is not a directory", id="file"),
    ],
)
async def test_repair_mode_only_relaxes_the_mode_check(
    local: LocalSandboxEnvironment,
    parent: Path,
    arrange: Callable[[Path], object],
    expected_fragment: str,
) -> None:
    target = parent / "fw"
    arrange(target)
    before = os.lstat(target)
    with pytest.raises(FrameworkDirectoryError, match=expected_fragment):
        await ensure_framework_directory(
            local, str(target), user=None, repair_mode=True
        )
    after = os.lstat(target)
    assert (after.st_ino, after.st_mode) == (before.st_ino, before.st_mode)


async def test_repair_mode_does_not_touch_directory_owned_by_another_uid(
    local: LocalSandboxEnvironment, tmp_path: Path
) -> None:
    """Pretend to be uid 4242 under root-owned /var/tmp: the directory is not ours."""
    bindir = _tool_dir(
        tmp_path, ["sh", "stat", "mkdir", "chmod", "pwd"], {"id": "echo 4242"}
    )
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    target = Path("/var/tmp") / f".inspect-fw-test-{uuid.uuid4().hex}"
    target.mkdir()
    target.chmod(0o755)
    try:
        with pytest.raises(
            FrameworkDirectoryError,
            match=f"owned by uid {os.getuid()}, expected uid 4242",
        ):
            await ensure_framework_directory(
                sandbox, str(target), user=None, repair_mode=True
            )
        assert _mode(target) == 0o755
    finally:
        shutil.rmtree(target, ignore_errors=True)


async def test_creation_failure_is_not_reported_as_untrustworthy(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    """An unwritable parent (or read-only filesystem) leaves nothing to remove."""
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user (root can write anywhere)")
    parent.chmod(0o500)
    try:
        for target in (parent / "fw", parent / "missing" / "fw"):
            with pytest.raises(
                FrameworkDirectoryError, match="Permission denied"
            ) as ei:
                await ensure_framework_directory(local, str(target), user=None)
            assert not isinstance(ei.value, FrameworkDirectoryNotFoundError)
            assert str(ei.value).startswith(
                f"Cannot create sandbox framework directory {target}: "
            )
            assert "cannot be trusted" not in str(ei.value)
            assert "Remove the entry" not in str(ei.value)
        assert list(parent.iterdir()) == []
    finally:
        parent.chmod(0o700)


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_chmod_after_mkdir(0o000), id="no-search-permission"),
        pytest.param(lambda p: p.write_text(""), id="regular-file"),
    ],
)
async def test_unenterable_parent_is_unavailable_not_violation(
    local: LocalSandboxEnvironment,
    parent: Path,
    arrange: Callable[[Path], object],
) -> None:
    """A parent that cannot be entered is an environment problem: nothing to remove."""
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user (root can enter anything)")
    blocked = parent / "blocked"
    arrange(blocked)
    try:
        for op in (ensure_framework_directory, verify_framework_directory):
            # dash reports only "can't cd to <dir>", so match our text, not errno's.
            with pytest.raises(
                FrameworkDirectoryUnavailableError,
                match=f"cannot enter parent directory {blocked}",
            ) as ei:
                await op(local, str(blocked / "fw"), user=None)
            assert "Remove the entry" not in str(ei.value)
    finally:
        if blocked.is_dir():
            blocked.chmod(0o700)


async def test_rejects_directory_owned_by_another_uid(
    local: LocalSandboxEnvironment,
) -> None:
    # /tmp is root-owned; the test user is (normally) not root.
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user")
    with pytest.raises(FrameworkDirectoryError, match="owned by uid 0, expected uid"):
        await exec_in_framework_directory(local, "/tmp", ["true"], user=None)


async def test_rejects_parent_owned_by_another_non_root_uid(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    """Pretend to be uid 4242: the test-user-owned parent is then someone else's."""
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user (a root-owned parent is accepted)")
    bindir = _tool_dir(
        tmp_path, ["sh", "stat", "mkdir", "chmod", "pwd"], {"id": "echo 4242"}
    )
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    target = parent / "fw"
    with pytest.raises(FrameworkDirectoryError, match="its owner could replace"):
        await ensure_framework_directory(sandbox, str(target), user=None)
    assert not target.exists()


async def test_rejects_running_as_a_uid_other_than_expected(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    """LocalSandboxEnvironment ignores `user`; expected_uid=0 must expose that."""
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user")
    target = parent / "fw"
    with pytest.raises(FrameworkDirectoryUserError) as excinfo:
        await ensure_framework_directory(
            local, str(target), user="root", expected_uid=0
        )
    assert f"running as uid {os.getuid()}, expected uid 0" in str(excinfo.value)
    assert "as the requested user root" in str(excinfo.value)
    assert not isinstance(excinfo.value, FrameworkDirectoryError)
    assert not target.exists()  # refused before creating anything

    with pytest.raises(FrameworkDirectoryUserError):
        await exec_in_framework_directory(
            local, str(parent), ["touch", "ran"], user=None, expected_uid=0
        )
    assert not (parent / "ran").exists()


async def test_accepts_matching_expected_uid(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    await ensure_framework_directory(
        local, str(target), user=None, expected_uid=os.getuid()
    )
    assert _mode(target) == 0o700
    result = await exec_in_framework_directory(
        local, str(target), ["id", "-u"], user=None, expected_uid=os.getuid()
    )
    assert result.stdout.strip() == str(os.getuid())


async def test_tool_warnings_on_stderr_do_not_corrupt_values(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    """`id`/`stat` stderr must not be folded into the uid or mode being compared."""
    real_id = shutil.which("id")
    real_stat = shutil.which("stat")
    assert real_id and real_stat
    bindir = _tool_dir(
        tmp_path,
        ["sh", "mkdir", "chmod", "pwd"],
        {
            "id": f'echo "id: spurious warning" >&2; exec {real_id} "$@"',
            "stat": f'echo "stat: spurious warning" >&2; exec {real_stat} "$@"',
        },
    )
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    target = parent / "fw"
    await ensure_framework_directory(
        sandbox, str(target), user=None, expected_uid=os.getuid()
    )
    assert _mode(target) == 0o700


async def test_garbage_from_id_is_unavailable_not_violation(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    bindir = _tool_dir(
        tmp_path, ["sh", "stat", "mkdir", "chmod", "pwd"], {"id": "echo not-a-uid"}
    )
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    target = parent / "fw"
    with pytest.raises(FrameworkDirectoryUnavailableError, match="not-a-uid"):
        await ensure_framework_directory(sandbox, str(target), user=None)
    assert not target.exists()


async def test_rejects_parent_that_lets_others_replace_the_directory(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    target.mkdir(mode=0o700)
    parent.chmod(0o777)
    with pytest.raises(FrameworkDirectoryError, match="other users could replace"):
        await ensure_framework_directory(local, str(target), user=None)


async def test_accepts_sticky_world_writable_parent_owned_by_user(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    parent.chmod(0o1777)
    await ensure_framework_directory(local, str(target), user=None)
    assert _mode(target) == 0o700


async def test_accepts_sticky_world_writable_parent_owned_by_root(
    local: LocalSandboxEnvironment,
) -> None:
    """The production shape: /var/tmp is root-owned 1777."""
    target = Path("/var/tmp") / f".inspect-fw-test-{uuid.uuid4().hex}"
    try:
        await ensure_framework_directory(local, str(target), user=None)
        assert _mode(target) == 0o700
        result = await exec_in_framework_directory(
            local, str(target), ["pwd", "-P"], user=None
        )
        assert result.stdout.strip() == str(target.resolve())
    finally:
        shutil.rmtree(target, ignore_errors=True)


async def test_exec_runs_with_verified_directory_as_cwd(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    result = await exec_in_framework_directory(
        local, str(target), ["sh", "-c", "pwd -P && touch marker"], user=None
    )
    assert result.success
    assert result.stdout.strip() == str(target.resolve())
    assert (target / "marker").exists()
    assert _VERIFIED_MARKER not in result.stderr


async def test_wrapped_command_stays_in_verified_directory_after_leaf_swap(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    """A hostile swap of the leaf after verification must not redirect writes.

    The command itself plays the attacker: from inside the verified cwd it renames
    the directory away and plants a symlink to a decoy at the original pathname,
    then writes through a relative path. The write must land in the directory that
    was verified (now under its new name), never in the decoy.
    """
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    decoy = tmp_path / "decoy"
    decoy.mkdir(mode=0o700)
    moved = parent / "moved"

    result = await exec_in_framework_directory(
        local,
        str(target),
        [
            "sh",
            "-c",
            'mv -- "$1" "$2" && ln -s -- "$3" "$1" && touch ./marker && pwd -P',
            "sh",
            str(target),
            str(moved),
            str(decoy),
        ],
        user=None,
    )
    assert result.success, result.stderr
    assert result.stdout.strip() == str(moved.resolve())
    assert (moved / "marker").exists()
    assert not (decoy / "marker").exists()
    assert target.is_symlink()
    # The pathname now names the attacker's symlink; a fresh check refuses it.
    with pytest.raises(FrameworkDirectoryError, match="symbolic link"):
        await verify_framework_directory(local, str(target), user=None)


async def test_wrapped_command_fails_cleanly_when_leaf_is_removed(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    """Removing the verified directory from under the command makes writes fail."""
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    result = await exec_in_framework_directory(
        local,
        str(target),
        ["sh", "-c", 'rmdir -- "$1" && touch ./marker', "sh", str(target)],
        user=None,
    )
    assert not result.success
    assert not target.exists()
    assert not (parent / "marker").exists()
    with pytest.raises(FrameworkDirectoryNotFoundError):
        await verify_framework_directory(local, str(target), user=None)


async def test_exec_passes_stdin_to_the_wrapped_command(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    """The script reads nothing from stdin, so `input` reaches the command whole."""
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    result = await exec_in_framework_directory(
        local,
        str(target),
        ["sh", "-c", "cat > ./from-stdin"],
        user=None,
        input="streamed\ncontent\n",
    )
    assert result.success, result.stderr
    assert (target / "from-stdin").read_text() == "streamed\ncontent\n"


async def test_exec_ignores_cdpath(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    decoy = tmp_path / "decoy" / "fw"
    decoy.mkdir(parents=True, mode=0o700)
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    sandbox = _EnvSandbox(local, {"CDPATH": f"{decoy.parent}:."})
    result = await exec_in_framework_directory(
        sandbox, str(target), ["pwd", "-P"], user=None
    )
    assert result.stdout.strip() == str(target.resolve())


async def test_inherited_path_is_not_consulted(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    """A utility that exists only on the sandbox's PATH must not be found.

    The inherited PATH here also carries an empty component (cwd, the parent while
    it is being checked) to show neither it nor the shim directory survives.
    """
    bindir = _tool_dir(tmp_path, [], {"frobnicate": 'touch "$PWD/ran-shim"'})
    sandbox = _EnvSandbox(local, {"PATH": f"{bindir}::{os.environ['PATH']}"})
    target = parent / "fw"
    await ensure_framework_directory(sandbox, str(target), user=None)
    result = await exec_in_framework_directory(
        sandbox, str(target), ["sh", "-c", 'printf %s "$PATH"'], user=None
    )
    assert result.stdout == _SCRIPT_PATH_LINE.removeprefix("PATH=")
    result = await exec_in_framework_directory(
        sandbox, str(target), ["frobnicate"], user=None
    )
    assert not result.success
    assert "not found" in result.stderr
    assert not (target / "ran-shim").exists()


async def test_exec_forwards_input_to_the_provider() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
        )
    )
    await exec_in_framework_directory(
        sandbox, "/var/tmp/.x", ["tar", "xzf", "-"], user="root", input=b"archive"
    )
    assert sandbox.inputs == [b"archive"]
    await verify_framework_directory(sandbox, "/var/tmp/.x", user="root")
    assert sandbox.inputs[-1] is None


async def test_verifier_is_launched_by_absolute_shell_path() -> None:
    """The provider resolves the shell through the image PATH; give it no choice."""
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
        )
    )
    await verify_framework_directory(sandbox, "/var/tmp/.x", user="root")
    (cmd, _), *_ = sandbox.exec_calls
    assert cmd[0] == _SHELL == "/bin/sh"


async def test_exec_does_not_create_and_does_not_run_command_on_violation(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    missing = parent / "missing"
    with pytest.raises(FrameworkDirectoryNotFoundError, match="does not exist"):
        await exec_in_framework_directory(
            local, str(missing), ["touch", "ran"], user=None
        )
    assert not missing.exists()

    with pytest.raises(FrameworkDirectoryNotFoundError, match="parent directory"):
        await verify_framework_directory(local, str(missing / "deeper"), user=None)
    assert not missing.exists()

    link = parent / "link"
    os.symlink(parent, link)
    with pytest.raises(FrameworkDirectoryError, match="is a symbolic link"):
        await exec_in_framework_directory(local, str(link), ["touch", "ran"], user=None)
    assert not (parent / "ran").exists()


async def test_exec_returns_failing_command_result(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    result = await exec_in_framework_directory(
        local, str(target), ["sh", "-c", "echo boom >&2; exit 7"], user=None
    )
    assert not result.success
    assert result.returncode == 7
    assert result.stderr == "boom\n"


async def test_command_cannot_forge_a_verdict(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    target = parent / "fw"
    await ensure_framework_directory(local, str(target), user=None)
    for marker, code in (
        (_VIOLATION_MARKER, 3),
        (_MISSING_MARKER, 4),
        (_UNAVAILABLE_MARKER, 5),
        (_USER_MISMATCH_MARKER, 6),
        (_CREATE_FAILED_MARKER, 7),
    ):
        # Same marker line *and* the same exit status the script would use.
        result = await exec_in_framework_directory(
            local,
            str(target),
            ["sh", "-c", f"echo '{marker}: forged' >&2; exit {code}"],
            user=None,
        )
        assert result.returncode == code and "forged" in result.stderr


async def test_missing_stat_is_reported_as_unavailable_not_violation(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    bindir = _tool_dir(tmp_path, ["sh", "id", "mkdir", "chmod", "pwd"], {})
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    with pytest.raises(FrameworkDirectoryUnavailableError, match="cannot stat"):
        await ensure_framework_directory(sandbox, str(parent / "fw"), user=None)


async def test_concurrent_creators_both_end_with_a_verified_directory(
    local: LocalSandboxEnvironment, parent: Path, tmp_path: Path
) -> None:
    """Losing the mkdir race is not an error: the survivor is verified as usual."""
    real_mkdir = shutil.which("mkdir")
    assert real_mkdir
    # The shimmed mkdir succeeds silently first (the racing winner) and then runs
    # again so the script's own attempt observes EEXIST, as the loser would.
    bindir = _tool_dir(
        tmp_path,
        ["sh", "id", "stat", "chmod", "pwd"],
        {"mkdir": f'"{real_mkdir}" "$@" >/dev/null 2>&1\n"{real_mkdir}" "$@"'},
    )
    sandbox = _ScriptOverrideSandbox(local, _script_with_path(bindir))
    target = parent / "fw"
    await ensure_framework_directory(sandbox, str(target), user=None)
    assert _mode(target) == 0o700


async def test_exec_requires_a_command(
    local: LocalSandboxEnvironment, parent: Path
) -> None:
    with pytest.raises(ValueError, match="cmd must not be empty"):
        await exec_in_framework_directory(local, str(parent / "fw"), [], user=None)


@pytest.mark.parametrize("path", ["relative/dir", "/", "/var/tmp/../x", "/.."])
def test_split_framework_path_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        split_framework_path(path)


def test_split_framework_path_normalizes() -> None:
    assert split_framework_path("/var/tmp/.x/") == FrameworkPath("/var/tmp", ".x")
    assert split_framework_path("/var/tmp/./.x") == FrameworkPath("/var/tmp", ".x")
    assert split_framework_path("/x") == FrameworkPath("/", "x")


def test_script_is_valid_posix_sh() -> None:
    subprocess.run(["sh", "-n", "-c", _SCRIPT], check=True)


async def test_violation_verdict_becomes_framework_directory_error() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=3,
            stdout="",
            stderr=f"{_VIOLATION_MARKER}: /var/tmp/.x is owned by uid 1111, expected uid 0\n",
        )
    )
    with pytest.raises(FrameworkDirectoryError) as excinfo:
        await ensure_framework_directory(sandbox, "/var/tmp/.x", user="root")
    assert not isinstance(excinfo.value, FrameworkDirectoryNotFoundError)
    assert "owned by uid 1111, expected uid 0" in str(excinfo.value)
    assert "/var/tmp/.x" in str(excinfo.value)
    # The request ran as the intended owner, via sh, with parent and leaf split.
    (cmd, user), *_ = sandbox.exec_calls
    assert user == "root"
    assert cmd[:2] == [_SHELL, "-c"]
    assert cmd[-2:] == ["/var/tmp", ".x"]


async def test_verdict_is_honoured_when_exit_status_is_not_propagated() -> None:
    """A provider that flattens exit statuses must not turn a violation into 'did not run'."""
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True,
            returncode=0,
            stdout="",
            stderr=f"{_VIOLATION_MARKER}: /var/tmp/.x is a symbolic link\n",
        )
    )
    with pytest.raises(FrameworkDirectoryError, match="symbolic link") as excinfo:
        await ensure_framework_directory(sandbox, "/var/tmp/.x", user="root")
    assert not isinstance(excinfo.value, FrameworkDirectoryNotFoundError)


async def test_unavailable_verdict_is_not_a_contract_violation() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=5,
            stdout="",
            stderr=f"sh: stat: not found\n{_UNAVAILABLE_MARKER}: cannot stat parent directory /var/tmp: sh: stat: not found\n",
        )
    )
    with pytest.raises(FrameworkDirectoryUnavailableError, match="stat: not found"):
        await ensure_framework_directory(sandbox, "/var/tmp/.x", user="root")


async def test_user_mismatch_verdict_becomes_user_error() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=6,
            stdout="",
            stderr=f"{_USER_MISMATCH_MARKER}: running as uid 1000, expected uid 0\n",
        )
    )
    with pytest.raises(FrameworkDirectoryUserError, match="expected uid 0") as excinfo:
        await ensure_framework_directory(
            sandbox, "/var/tmp/.x", user="root", expected_uid=0
        )
    assert not isinstance(
        excinfo.value, (FrameworkDirectoryError, FrameworkDirectoryUnavailableError)
    )
    # The expectation is passed to the script ahead of the create and repair flags.
    (cmd, user), *_ = sandbox.exec_calls
    assert user == "root"
    assert cmd[-5:] == ["0", "1", "0", "/var/tmp", ".x"]


async def test_no_expected_uid_passes_an_empty_expectation() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
        )
    )
    await verify_framework_directory(sandbox, "/var/tmp/.x", user=None)
    (cmd, _), *_ = sandbox.exec_calls
    assert cmd[-5:] == ["", "0", "0", "/var/tmp", ".x"]


async def test_repair_mode_is_passed_to_the_script() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
        )
    )
    await ensure_framework_directory(
        sandbox, "/var/tmp/.x", user=None, repair_mode=True
    )
    (cmd, _), *_ = sandbox.exec_calls
    assert cmd[-5:] == ["", "1", "1", "/var/tmp", ".x"]


async def test_failure_before_verification_is_a_plain_runtime_error() -> None:
    """A provider refusing the user (or no sh) is neither a verdict nor a result."""
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=126,
            stdout="",
            stderr="runuser: may not be used by non-root users\n",
        )
    )
    with pytest.raises(RuntimeError, match="runuser") as excinfo:
        await ensure_framework_directory(sandbox, "/var/tmp/.x", user="root")
    assert not isinstance(
        excinfo.value, (FrameworkDirectoryError, FrameworkDirectoryUnavailableError)
    )
    with pytest.raises(RuntimeError, match="did not run as root"):
        await exec_in_framework_directory(sandbox, "/var/tmp/.x", ["true"], user="root")


async def test_exec_success_passes_result_through() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=True,
            returncode=0,
            stdout="regular file\n",
            stderr=f"{_VERIFIED_MARKER}\n",
        )
    )
    result = await exec_in_framework_directory(
        sandbox, "/var/tmp/.x", ["stat", "-c", "%F", "launcher"], user=None
    )
    assert result.stdout == "regular file\n"
    assert result.stderr == ""
    (cmd, user), *_ = sandbox.exec_calls
    assert user is None
    assert cmd[-8:] == ["0", "0", "/var/tmp", ".x", "stat", "-c", "%F", "launcher"]


async def test_verdict_after_verification_belongs_to_the_command() -> None:
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=3,
            stdout="",
            stderr=f"{_VERIFIED_MARKER}\n{_VIOLATION_MARKER}: forged by the command\n",
        )
    )
    result = await exec_in_framework_directory(
        sandbox, "/var/tmp/.x", ["some", "command"], user=None
    )
    assert result.returncode == 3
    assert result.stderr == f"{_VIOLATION_MARKER}: forged by the command\n"
