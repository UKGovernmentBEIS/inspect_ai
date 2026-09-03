import ast
import concurrent.futures
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from argparse import Namespace
from collections.abc import AsyncIterator, Iterator
from io import StringIO
from pathlib import Path
from typing import Callable, Literal, NamedTuple, overload
from uuid import uuid4

import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent._human import install as human_install
from inspect_ai.agent._human.agent import human_cli
from inspect_ai.agent._human.commands import submit
from inspect_ai.agent._human.commands.submit import QuitCommand, SubmitCommand
from inspect_ai.agent._human.install import (
    _BASHRC_APPEND_SCRIPT,
    BASHRC,
    BASHRC_MARKER,
    HUMAN_AGENT_DIR,
    TASK_PY,
    append_bashrc,
    human_agent_bashrc,
    human_agent_commands,
    install_human_agent,
)
from inspect_ai.util._sandbox._framework_directory import (
    _SCRIPT,
    _SHELL,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._subprocess import ExecResult


@pytest.mark.parametrize(
    ("command", "args", "expected_calls"),
    [
        (QuitCommand(False), Namespace(), []),
        (
            SubmitCommand(False),
            Namespace(answer=None),
            [("validate", {"answer": None})],
        ),
    ],
)
def test_session_end_commands_decline_on_eof(
    command: QuitCommand | SubmitCommand,
    args: Namespace,
    expected_calls: list[tuple[str, dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def call_human_agent(method: str, **params: object) -> None:
        calls.append((method, params))

    monkeypatch.setattr(submit, "call_human_agent", call_human_agent)
    monkeypatch.setattr(sys, "stdin", StringIO())

    command.cli(args)

    assert calls == expected_calls


# ---------------------------------------------------------------------------
# install_human_agent() against a scripted sandbox
# ---------------------------------------------------------------------------

OK = ExecResult(success=True, returncode=0, stdout="", stderr="")
VERIFIED = ExecResult(
    success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
)
"""Helper result: verification passed and the wrapped command (if any) succeeded."""
REGULAR_TASK_PY = ExecResult(
    success=True,
    returncode=0,
    stdout="81ed\n",  # stat -c %f of a 0755 regular file
    stderr=f"{_VERIFIED_MARKER}\n",
)
NO_TASK_PY = ExecResult(
    success=True, returncode=0, stdout="missing\n", stderr=f"{_VERIFIED_MARKER}\n"
)
NOT_ROOT = ExecResult(
    success=False,
    returncode=6,
    stdout="",
    stderr=f"{_USER_MISMATCH_MARKER}: running as uid 1000, expected uid 0\n",
)
"""A provider that accepted user="root" but ran the helper as someone else."""


def violation(message: str) -> ExecResult[str]:
    return ExecResult(
        success=False,
        returncode=3,
        stdout="",
        stderr=f"{_VIOLATION_MARKER}: {message}\n",
    )


HUMAN_AGENT_LEAF = HUMAN_AGENT_DIR.rsplit("/", 1)[1]


def is_helper_call(cmd: list[str]) -> bool:
    return cmd[:3] == [_SHELL, "-c", _SCRIPT] and HUMAN_AGENT_LEAF in cmd


def is_bashrc_call(cmd: list[str]) -> bool:
    return cmd[:3] == [_SHELL, "-c", _BASHRC_APPEND_SCRIPT]


def wrapped_command(cmd: list[str]) -> list[str]:
    """The command a framework-directory call execs after verification."""
    assert is_helper_call(cmd)
    return cmd[cmd.index(HUMAN_AGENT_LEAF) + 1 :]


def _wrapped_shell_script(cmd: list[str], name: str) -> str | None:
    """The `sh -c` script a helper call runs against ``name``, if it is one."""
    if not is_helper_call(cmd):
        return None
    wrapped = wrapped_command(cmd)
    if wrapped[:2] == ["sh", "-c"] and wrapped[3:] == ["sh", name]:
        return wrapped[2]
    return None


def is_task_py_probe(cmd: list[str]) -> bool:
    script = _wrapped_shell_script(cmd, TASK_PY)
    return script is not None and "stat -c %f" in script


def is_task_py_write(cmd: list[str]) -> bool:
    script = _wrapped_shell_script(cmd, TASK_PY)
    return script is not None and "cat >" in script


class HelperFlags(NamedTuple):
    """The fixed arguments a framework-directory call passes ahead of the path."""

    expected_uid: str
    create: str
    repair: str
    mode: str


def helper_flags(cmd: list[str]) -> HelperFlags:
    assert is_helper_call(cmd)
    leaf = cmd.index(HUMAN_AGENT_LEAF)
    return HelperFlags(*cmd[leaf - 5 : leaf - 1])


ROOT_CREATE = HelperFlags(expected_uid="0", create="1", repair="0", mode="755")
ROOT_CHECK = HelperFlags(expected_uid="0", create="0", repair="0", mode="755")
DEFAULT_CREATE = HelperFlags(expected_uid="", create="1", repair="0", mode="755")
DEFAULT_CHECK = HelperFlags(expected_uid="", create="0", repair="0", mode="755")


def fresh_install(cmd: list[str], user: str | None) -> ExecResult[str]:
    """Root works, the directory verifies, and task.py is not there yet."""
    if is_task_py_probe(cmd):
        return NO_TASK_PY
    if is_helper_call(cmd):
        return VERIFIED
    return OK


@pytest.mark.parametrize("user", ["root", "nonroot", None])
async def test_install_writes_task_py_into_verified_root_dir_after_bashrc(
    user: str | None,
) -> None:
    sandbox = CannedSandbox(fresh_install)
    await install_human_agent(user, [], "extra bashrc", False, sandbox_env=sandbox)

    (
        (ensure, ensure_user),
        (detect, detect_user),
        (bashrc, bashrc_user),
        (
            write,
            write_user,
        ),
    ) = sandbox.exec_calls

    # Directory created (or adopted) as root, insisting on uid 0, in the traversable
    # mode the login user needs, and never repaired.
    assert ensure_user == "root"
    assert wrapped_command(ensure) == []
    assert helper_flags(ensure) == ROOT_CREATE

    # "Installed" is decided by task.py inside the verified directory.
    assert detect_user == "root"
    assert is_task_py_probe(detect)
    assert helper_flags(detect) == ROOT_CHECK

    # The .bashrc append runs as the login user with the content on stdin.
    assert bashrc_user == user
    assert is_bashrc_call(bashrc)
    assert bashrc[3:] == ["sh", BASHRC, user or "", BASHRC_MARKER]
    bash_rc = human_agent_bashrc([], "extra bashrc", False)
    assert sandbox.inputs[2] == bash_rc
    assert BASHRC_MARKER in bash_rc

    # task.py is written by root inside the verified directory, by relative name,
    # with the content on stdin, made world-readable and executable, and published
    # under its final name only once complete.
    assert write_user == "root"
    assert helper_flags(write) == ROOT_CHECK
    assert is_task_py_write(write)
    script = wrapped_command(write)[2]
    assert "chmod 0755" in script and "set -C" in script
    assert script.index("cat >") < script.index("chmod 0755") < script.index("ln ")
    assert sandbox.inputs[3] == human_agent_commands([])

    # Every command is launched through the absolute shell path; nothing is staged,
    # chowned, or executed from a directory the login user could replace.
    assert all(cmd[0] == _SHELL for cmd, _ in sandbox.exec_calls)
    assert sandbox.written == []


async def test_install_is_skipped_when_task_py_is_already_a_regular_file() -> None:
    sandbox = CannedSandbox(
        lambda cmd, user: REGULAR_TASK_PY if is_helper_call(cmd) else OK
    )
    await install_human_agent("nonroot", [], None, True, sandbox_env=sandbox)

    assert [user for _, user in sandbox.exec_calls] == ["root", "root"]
    assert is_task_py_probe(sandbox.exec_calls[1][0])
    assert not any(is_bashrc_call(cmd) for cmd, _ in sandbox.exec_calls)
    assert sandbox.inputs == [None, None]


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(
            f"{HUMAN_AGENT_DIR} is owned by uid 1000, expected uid 0",
            id="user-owned-directory",
        ),
        pytest.param(f"{HUMAN_AGENT_DIR} is a symbolic link", id="symlink"),
        pytest.param(f"{HUMAN_AGENT_DIR} is not a directory", id="regular-file"),
        pytest.param(
            f"{HUMAN_AGENT_DIR} has mode 777, expected 755", id="world-writable"
        ),
    ],
)
async def test_install_aborts_on_untrusted_dir_without_touching_anything(
    message: str,
) -> None:
    """A pre-existing entry that fails the contract is an error, not a skip."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_helper_call(cmd) and user == "root":
            return violation(message)
        return fresh_install(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(FrameworkDirectoryError, match=re.escape(message)):
        await install_human_agent("nonroot", [], None, True, sandbox_env=sandbox)

    # One root-side check and nothing else: no default-user fallback, no .bashrc
    # append, no write.
    assert [user for _, user in sandbox.exec_calls] == ["root"]
    assert wrapped_command(sandbox.exec_calls[0][0]) == []
    assert sandbox.inputs == [None]
    assert sandbox.written == []


@pytest.mark.parametrize(
    "root_failure",
    [
        pytest.param(
            RuntimeError("runuser: may not be used by non-root users"),
            id="provider-raises",
        ),
        pytest.param(NOT_ROOT, id="provider-runs-root-as-default-user"),
        pytest.param(
            ExecResult(
                success=False,
                returncode=126,
                stdout="",
                stderr="unable to find user root: no matching entries in passwd file\n",
            ),
            id="provider-fails-with-status",
        ),
    ],
)
async def test_rootless_install_owns_dir_as_default_user(
    root_failure: Exception | ExecResult[str],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            if isinstance(root_failure, Exception):
                raise root_failure
            return root_failure
        return fresh_install(cmd, user)

    sandbox = CannedSandbox(policy)
    await install_human_agent(None, [], None, False, sandbox_env=sandbox)

    users = [user for _, user in sandbox.exec_calls]
    assert users == ["root", None, None, None, None]
    root_probe, ensure, detect, bashrc, write = (cmd for cmd, _ in sandbox.exec_calls)
    assert helper_flags(root_probe) == ROOT_CREATE
    # Default-user checks carry no uid expectation (the host cannot know it), and a
    # wrong-mode directory is still refused rather than repaired: the fallback may
    # itself be running as root.
    assert helper_flags(ensure) == DEFAULT_CREATE
    assert helper_flags(detect) == DEFAULT_CHECK
    assert is_task_py_probe(detect)
    assert is_bashrc_call(bashrc)
    assert helper_flags(write) == DEFAULT_CHECK
    assert is_task_py_write(write)


async def test_rootless_install_still_refuses_an_untrusted_dir() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            raise RuntimeError("no root")
        if is_helper_call(cmd):
            return violation(f"{HUMAN_AGENT_DIR} is a symbolic link")
        return OK

    sandbox = CannedSandbox(policy)
    with pytest.raises(FrameworkDirectoryError, match="symbolic link"):
        await install_human_agent(None, [], None, False, sandbox_env=sandbox)
    assert not any(is_bashrc_call(cmd) for cmd, _ in sandbox.exec_calls)
    assert sandbox.inputs == [None, None]


@pytest.mark.parametrize(
    "probe_result, expected",
    [
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="a1ff\n",
                stderr=f"{_VERIFIED_MARKER}\n",
            ),
            "not a regular file",
            id="symlink",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="41ed\n",
                stderr=f"{_VERIFIED_MARKER}\n",
            ),
            "not a regular file",
            id="directory",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="regular file\n",
                stderr=f"{_VERIFIED_MARKER}\n",
            ),
            "Unexpected output",
            id="garbage",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\nstat: cannot statx 'task.py': Input/output error\n",
            ),
            "Input/output error",
            id="probe-failed",
        ),
    ],
)
async def test_install_errors_when_task_py_cannot_be_confirmed_absent(
    probe_result: ExecResult[str], expected: str
) -> None:
    """Anything but "missing" or a regular file is an error, never an install-over."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_task_py_probe(cmd):
            return probe_result
        return fresh_install(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(RuntimeError, match=expected):
        await install_human_agent("nonroot", [], None, False, sandbox_env=sandbox)
    assert len(sandbox.exec_calls) == 2
    assert not any(is_bashrc_call(cmd) for cmd, _ in sandbox.exec_calls)


async def test_refused_bashrc_append_aborts_before_task_py_is_written() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_bashrc_call(cmd):
            return ExecResult(
                success=False,
                returncode=3,
                stdout="",
                stderr="refusing to append to /home/nonroot/.bashrc: it is a symbolic link\n",
            )
        return fresh_install(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(RuntimeError, match="symbolic link") as excinfo:
        await install_human_agent("nonroot", [], None, False, sandbox_env=sandbox)
    assert "for user nonroot" in str(excinfo.value)
    assert not any(is_task_py_write(cmd) for cmd, _ in sandbox.exec_calls)
    # Nothing was written into the directory, so a retry starts over.
    assert [user for _, user in sandbox.exec_calls] == ["root", "root", "nonroot"]
    assert sandbox.inputs[:2] == [None, None]


async def test_failed_task_py_write_is_reported() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_task_py_write(cmd):
            return ExecResult(
                success=False,
                returncode=2,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\nsh: 1: cannot create task.py: File exists\n",
            )
        return fresh_install(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(RuntimeError, match="File exists"):
        await install_human_agent("root", [], None, False, sandbox_env=sandbox)


def test_installer_source_runs_nothing_outside_the_helper_and_bashrc_scripts() -> None:
    """Mechanical guard: install.py issues no raw mkdir/chown/chmod/bash/rm/tee/cp.

    Every ``exec`` in the module must launch the absolute shell with either the
    framework-directory helper script or the ``.bashrc`` append script; the only
    ``chmod`` is inside a command the helper runs in the verified directory.
    """
    source = Path(human_install.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {"mkdir", "chown", "chmod", "bash", "rm", "tee", "cp", "mv"}
    # Docstrings describe what the installer no longer does; only code counts.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant):
                assert first.value not in forbidden, ast.unparse(node)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            assert node.value not in forbidden, node.value
            for fragment in ("bash ./", "install.sh", "chown", "human_agent_install"):
                assert fragment not in node.value, node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "exec":
                argv = node.args[0]
                assert isinstance(argv, ast.List), ast.unparse(node)
                assert isinstance(argv.elts[0], ast.Name), ast.unparse(node)
                assert argv.elts[0].id == "_SHELL", ast.unparse(node)
    assert not hasattr(human_install, "INSTALL_DIR")
    assert not hasattr(human_install, "human_agent_install_sh")


# ---------------------------------------------------------------------------
# The .bashrc append script, run for real via LocalSandboxEnvironment
# ---------------------------------------------------------------------------


class _HomeSandbox(SandboxEnvironment):
    """Runs the .bashrc append script with ``getent`` reporting a chosen home.

    The script pins its PATH to the system directories, so the only way to give it
    a different home directory than the test user's real one is to replace that
    line with a shim directory whose ``getent`` answers for ``home``.
    """

    def __init__(self, inner: SandboxEnvironment, home: Path, tmp_path: Path) -> None:
        super().__init__()
        self.inner = inner
        bindir = tmp_path / "bin"
        bindir.mkdir()
        for tool in ("id", "cut", "cat", "grep"):
            found = shutil.which(tool)
            assert found, f"{tool} not found on host"
            os.symlink(found, bindir / tool)
        self.getent_lookups = tmp_path / "getent-lookups"
        (bindir / "getent").write_text(
            f'#!/bin/sh\necho "$2" >> "{self.getent_lookups}"\n'
            f'echo "user:x:1000:1000::{home}:/bin/sh"\n'
        )
        (bindir / "getent").chmod(0o700)
        path_line = "PATH=/usr/sbin:/usr/bin:/sbin:/bin"
        assert path_line in _BASHRC_APPEND_SCRIPT
        self.script = _BASHRC_APPEND_SCRIPT.replace(path_line, f"PATH={bindir}")

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
        assert cmd[:3] == [_SHELL, "-c", _BASHRC_APPEND_SCRIPT]
        return await self.inner.exec([_SHELL, "-c", self.script, *cmd[3:]], input)

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


def test_bashrc_append_script_is_valid_posix_sh() -> None:
    subprocess.run(["sh", "-n", "-c", _BASHRC_APPEND_SCRIPT], check=True)


@pytest.fixture
def home_sandbox(tmp_path: Path) -> Iterator[tuple[_HomeSandbox, Path]]:
    if sys.platform != "linux":
        pytest.skip("runs the append script through the local sandbox on Linux")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    local = LocalSandboxEnvironment()
    try:
        yield _HomeSandbox(local, home, tmp_path), home
    finally:
        local.directory.cleanup()


async def test_bashrc_append_creates_or_extends_a_regular_file(
    home_sandbox: tuple[_HomeSandbox, Path],
) -> None:
    sandbox, home = home_sandbox
    await append_bashrc(sandbox, None, "first\n")
    assert (home / BASHRC).read_text() == "first\n"
    (home / BASHRC).write_text("existing\n")
    await append_bashrc(sandbox, None, "second\n")
    assert (home / BASHRC).read_text() == "existing\nsecond\n"
    # The default user is looked up by uid, a named login user by name.
    assert sandbox.getent_lookups.read_text() == f"{os.getuid()}\n{os.getuid()}\n"
    await append_bashrc(sandbox, "someone", "third\n")
    assert sandbox.getent_lookups.read_text().splitlines()[-1] == "someone"
    assert (home / BASHRC).read_text() == "existing\nsecond\nthird\n"


async def test_bashrc_append_is_skipped_when_the_block_is_already_there(
    home_sandbox: tuple[_HomeSandbox, Path],
) -> None:
    sandbox, home = home_sandbox
    block = human_agent_bashrc([], None, False)
    await append_bashrc(sandbox, None, block)
    once = (home / BASHRC).read_text()
    assert once.count(BASHRC_MARKER) == 1
    await append_bashrc(sandbox, None, block)
    assert (home / BASHRC).read_text() == once
    # Only a whole line equal to the marker counts, not a mention of it.
    (home / BASHRC).write_text(f"# {BASHRC_MARKER} (removed)\n")
    await append_bashrc(sandbox, None, block)
    assert (home / BASHRC).read_text().count(BASHRC_MARKER) == 2


async def test_task_py_probe_and_write_against_a_real_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe and the atomic write run for real through the local sandbox."""
    if sys.platform != "linux":
        pytest.skip("runs the helper script through the local sandbox on Linux")
    parent = tmp_path / "opt"
    parent.mkdir(mode=0o755)
    target = parent / "human_agent"
    monkeypatch.setattr(human_install, "HUMAN_AGENT_DIR", str(target))
    local = LocalSandboxEnvironment()
    try:
        assert await human_install._ensure_human_agent_dir(local) is None
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
        assert await human_install._task_py_installed(local, None) is False

        await human_install._write_task_py(local, None, "print('hi')\n")
        task_py = target / TASK_PY
        assert task_py.read_text() == "print('hi')\n"
        assert stat.S_IMODE(task_py.stat().st_mode) == 0o755
        assert sorted(p.name for p in target.iterdir()) == [TASK_PY]
        assert await human_install._task_py_installed(local, None) is True

        # Publishing never replaces an existing task.py, and leaves no temp file.
        with pytest.raises(RuntimeError, match="File exists"):
            await human_install._write_task_py(local, None, "print('bye')\n")
        assert task_py.read_text() == "print('hi')\n"
        assert sorted(p.name for p in target.iterdir()) == [TASK_PY]

        # Anything other than a regular file at task.py is an error, not "installed".
        task_py.unlink()
        task_py.mkdir()
        with pytest.raises(RuntimeError, match="not a regular file"):
            await human_install._task_py_installed(local, None)
    finally:
        local.directory.cleanup()


@pytest.mark.parametrize(
    "arrange, expected",
    [
        pytest.param(
            lambda bashrc, target: os.symlink(target, bashrc),
            "is a symbolic link",
            id="symlink",
        ),
        pytest.param(
            lambda bashrc, target: os.symlink(target.parent / "missing", bashrc),
            "is a symbolic link",
            id="dangling-symlink",
        ),
        pytest.param(
            lambda bashrc, target: bashrc.mkdir(),
            "is not a regular file",
            id="directory",
        ),
    ],
)
async def test_bashrc_append_refuses_a_non_regular_bashrc(
    home_sandbox: tuple[_HomeSandbox, Path],
    tmp_path: Path,
    arrange: Callable[[Path, Path], object],
    expected: str,
) -> None:
    sandbox, home = home_sandbox
    target = tmp_path / "target"
    target.write_text("")
    arrange(home / BASHRC, target)
    with pytest.raises(RuntimeError, match=expected):
        await append_bashrc(sandbox, None, "payload\n")
    assert target.read_text() == ""
    assert not list(home.glob("*payload*"))
    for entry in home.iterdir():
        if entry.is_file() and not entry.is_symlink():
            assert "payload" not in entry.read_text()


# ---------------------------------------------------------------------------
# Docker: the real thing, with a non-root login user
# ---------------------------------------------------------------------------

HUMAN_COMPOSE = (Path(__file__).parent / "compose.human.yaml").as_posix()


@pytest.fixture
async def docker_sandbox() -> AsyncIterator[SandboxEnvironment]:
    task_name = f"human_agent_install_{uuid4().hex[:8]}"
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=HUMAN_COMPOSE)
    environments = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=HUMAN_COMPOSE, metadata={}
    )
    try:
        yield environments["default"]
    finally:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name,
            config=HUMAN_COMPOSE,
            environments=environments,
            interrupted=False,
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=HUMAN_COMPOSE, cleanup=True
        )


async def _root_sh(sandbox: SandboxEnvironment, script: str) -> str:
    result = await sandbox.exec(["sh", "-c", script], user="root")
    assert result.success, result.stderr
    return result.stdout


async def _stat(sandbox: SandboxEnvironment, path: str) -> str:
    """``<type-and-mode> <uid>`` of ``path`` itself (symlinks are not followed)."""
    return (await _root_sh(sandbox, f"stat -c '%f %u' {path}")).strip()


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_install_for_nonroot_user_and_reinstall_is_skipped(
    docker_sandbox: SandboxEnvironment,
) -> None:
    before = await _root_sh(docker_sandbox, "cat /home/nonroot/.bashrc")
    await install_human_agent("nonroot", [], None, True, sandbox_env=docker_sandbox)

    # Root-owned traversable directory holding a root-owned 0755 task.py.
    assert await _stat(docker_sandbox, HUMAN_AGENT_DIR) == "41ed 0"
    assert await _stat(docker_sandbox, f"{HUMAN_AGENT_DIR}/{TASK_PY}") == "81ed 0"
    # The login user can read it and it parses (py_compile would try to write a
    # __pycache__ into the root-owned directory, so parse it in memory instead),
    # and only that user's .bashrc changed.
    check = await docker_sandbox.exec(
        [
            "python3",
            "-c",
            "import ast, sys; ast.parse(open(sys.argv[1]).read())",
            f"{HUMAN_AGENT_DIR}/{TASK_PY}",
        ],
        user="nonroot",
    )
    assert check.success, check.stderr
    after = await _root_sh(docker_sandbox, "cat /home/nonroot/.bashrc")
    assert after.startswith(before)
    assert after.count("### Inspect Human Agent Setup") == 1
    assert f"alias task='python3 {HUMAN_AGENT_DIR}/{TASK_PY}'" in after
    assert "Inspect Human Agent" not in await _root_sh(
        docker_sandbox, "cat /root/.bashrc 2>/dev/null || true"
    )

    # A second installation finds task.py and appends nothing.
    await install_human_agent("nonroot", [], None, True, sandbox_env=docker_sandbox)
    assert await _root_sh(docker_sandbox, "cat /home/nonroot/.bashrc") == after


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_install_for_default_root_user(
    docker_sandbox: SandboxEnvironment,
) -> None:
    await install_human_agent(None, [], None, False, sandbox_env=docker_sandbox)
    assert await _stat(docker_sandbox, f"{HUMAN_AGENT_DIR}/{TASK_PY}") == "81ed 0"
    root_bashrc = await _root_sh(docker_sandbox, "cat /root/.bashrc")
    assert root_bashrc.count("### Inspect Human Agent Setup") == 1
    assert "Inspect Human Agent" not in await _root_sh(
        docker_sandbox, "cat /home/nonroot/.bashrc"
    )


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_install_refuses_planted_human_agent_dir(
    docker_sandbox: SandboxEnvironment,
) -> None:
    """A pre-planted entry aborts installation with the helper's message and no writes."""
    bashrc_before = await _root_sh(docker_sandbox, "cat /home/nonroot/.bashrc")
    for arrange, expected in [
        (
            f"mkdir {HUMAN_AGENT_DIR} && chown nonroot {HUMAN_AGENT_DIR}",
            "is owned by uid 1000, expected uid 0",
        ),
        (
            f"mkdir -p /home/nonroot/decoy && ln -s /home/nonroot/decoy {HUMAN_AGENT_DIR}",
            "is a symbolic link",
        ),
        (f"touch {HUMAN_AGENT_DIR}", "is not a directory"),
    ]:
        await _root_sh(docker_sandbox, arrange)
        before = await _stat(docker_sandbox, HUMAN_AGENT_DIR)
        with pytest.raises(FrameworkDirectoryError, match=expected):
            await install_human_agent(
                "nonroot", [], None, True, sandbox_env=docker_sandbox
            )
        # The planted entry is untouched: no chown, no chmod, nothing written
        # through it, and the login user's .bashrc is unchanged.
        assert await _stat(docker_sandbox, HUMAN_AGENT_DIR) == before
        listing = await _root_sh(
            docker_sandbox,
            f"ls -A {HUMAN_AGENT_DIR} /home/nonroot/decoy 2>/dev/null || true",
        )
        assert TASK_PY not in listing
        assert (
            await _root_sh(docker_sandbox, "cat /home/nonroot/.bashrc") == bashrc_before
        )
        await _root_sh(docker_sandbox, f"rm -rf {HUMAN_AGENT_DIR} /home/nonroot/decoy")


@pytest.mark.slow
@skip_if_no_docker
async def test_docker_install_refuses_bashrc_symlink(
    docker_sandbox: SandboxEnvironment,
) -> None:
    """The login user's .bashrc pointing at a root-owned file is refused, not followed."""
    await _root_sh(
        docker_sandbox,
        "touch /root/target && chmod 644 /root/target && "
        "rm /home/nonroot/.bashrc && ln -s /root/target /home/nonroot/.bashrc",
    )
    with pytest.raises(RuntimeError, match="symbolic link"):
        await install_human_agent("nonroot", [], None, True, sandbox_env=docker_sandbox)
    assert await _root_sh(docker_sandbox, "cat /root/target") == ""
    assert await _stat(docker_sandbox, "/home/nonroot/.bashrc") == "a1ff 0"
    # Nothing was written into the (verified, root-owned) directory either.
    assert TASK_PY not in await _root_sh(docker_sandbox, f"ls -A {HUMAN_AGENT_DIR}")


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize("user", ["root", "nonroot", None])
def test_human_cli(capsys: pytest.CaptureFixture[str], user: str | None):
    def run_eval():
        task = Task(
            solver=human_cli(user=user),
            sandbox=(
                "docker",
                (Path(__file__).parent / "compose.human.yaml").as_posix(),
            ),
        )
        return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        out = ""
        container_name = None
        for _ in range(10):
            out += capsys.readouterr().out
            if match := re.search(r"inspect-task-\S+-default-1", out):
                container_name = match.group(0)
                break
            time.sleep(1)

        if not container_name:
            raise Exception("Failed to find container name")

        docker_exec = [
            "docker",
            "exec",
            *(["-u", user] if user else []),
            container_name,
            "bash",
            "-l",
            "-c",
        ]

        human_agent_found = False
        for _ in range(10):
            result = subprocess.run(
                docker_exec
                + ["ls /var/tmp/sandbox-services/human_agent/human_agent.py"]
            )
            if result.returncode == 0:
                human_agent_found = True
                break
            time.sleep(1)

        if not human_agent_found:
            raise Exception("Human agent sandbox service not found")

        subprocess.check_call(docker_exec + ["python3 /opt/human_agent/task.py start"])
        subprocess.check_call(
            docker_exec
            + [
                'echo -e "y\\n" | python3 /opt/human_agent/task.py submit "test"',
            ],
        )

        done, _ = concurrent.futures.wait([future], timeout=20)
        if future in done:
            log = future.result()
            assert log.status == "success"
            assert log.samples[0].output.choices[0].message.content == "test"
        else:
            raise Exception("eval() did not complete within timeout")


@pytest.mark.slow
@skip_if_no_docker
def test_human_cli_submit_no_answer(capsys: pytest.CaptureFixture[str]):
    """Test that submitting without an answer completes the task when answer=False."""

    def run_eval():
        task = Task(
            solver=human_cli(answer=False),
            sandbox=(
                "docker",
                (Path(__file__).parent / "compose.human.yaml").as_posix(),
            ),
        )
        return eval(task, display="plain")[0]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(run_eval)

        out = ""
        container_name = None
        for _ in range(10):
            out += capsys.readouterr().out
            if match := re.search(r"inspect-task-\S+-default-1", out):
                container_name = match.group(0)
                break
            time.sleep(1)

        if not container_name:
            raise Exception("Failed to find container name")

        docker_exec = [
            "docker",
            "exec",
            container_name,
            "bash",
            "-l",
            "-c",
        ]

        human_agent_found = False
        for _ in range(10):
            result = subprocess.run(
                docker_exec
                + ["ls /var/tmp/sandbox-services/human_agent/human_agent.py"]
            )
            if result.returncode == 0:
                human_agent_found = True
                break
            time.sleep(1)

        if not human_agent_found:
            raise Exception("Human agent sandbox service not found")

        subprocess.check_call(docker_exec + ["python3 /opt/human_agent/task.py start"])
        # Submit without an answer - this should complete the task when answer=False
        subprocess.check_call(
            docker_exec
            + [
                'echo -e "y\\n" | python3 /opt/human_agent/task.py submit',
            ],
        )

        done, _ = concurrent.futures.wait([future], timeout=5)
        if future in done:
            log = future.result()
            assert log.status == "success"
            assert log.samples[0].output.choices[0].message.content == ""
        else:
            raise Exception("eval() did not complete within timeout")
