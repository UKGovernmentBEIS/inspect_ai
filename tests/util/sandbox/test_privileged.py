"""Tests for the pinned-``PATH`` helpers that run Inspect's own commands in a sandbox.

Three layers: the argv the helpers build; the helpers run for real through
``LocalSandboxEnvironment`` against a simulated image environment whose ``PATH``
puts a directory of forged utilities first (POSIX hosts only); and a Docker
acceptance test (slow) against an image built that way, covering the provider's
own resolution and its ``timeout`` wrapper. A mechanical guard over ``src`` keeps
new privileged call sites from reintroducing a bare ``sh`` or a relative command
run as root.
"""

import ast
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Literal, overload

import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox._framework_directory import (
    ensure_framework_directory,
    exec_in_framework_directory,
)
from inspect_ai.util._sandbox._privileged import (
    IMAGE_PATH_VARIABLE,
    SHELL_PATH,
    SYSTEM_PATH,
    pinned_command,
    pinned_env,
    pinned_shell_command,
    privileged_exec,
    privileged_shell,
)
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._subprocess import ExecResult

OK = ExecResult(success=True, returncode=0, stdout="", stderr="")

# ---------------------------------------------------------------------------
# The argv the helpers build
# ---------------------------------------------------------------------------


def test_pinned_command_launches_absolute_shell_and_pins_path() -> None:
    cmd = pinned_command(["rm", "-f", "--", "/var/tmp/x"])
    assert cmd[:2] == [SHELL_PATH, "-c"]
    assert SHELL_PATH == "/bin/sh"
    assert f"PATH={SYSTEM_PATH}" in cmd[2]
    assert 'exec "$@"' in cmd[2]
    assert cmd[3:] == ["sh", "rm", "-f", "--", "/var/tmp/x"]


def test_pinned_command_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="empty"):
        pinned_command([])


def test_pinned_shell_command_prepends_pin_and_passes_args() -> None:
    cmd = pinned_shell_command('set -e; rm -f -- "$1"', "/var/tmp/x", "second")
    assert cmd[:2] == [SHELL_PATH, "-c"]
    prologue, script = cmd[2].rsplit("\n", 1)
    assert prologue.splitlines() == [
        f"{IMAGE_PATH_VARIABLE}=${{PATH-}}",
        f"PATH={SYSTEM_PATH}",
        "export PATH",
        "unset CDPATH",
    ]
    assert script == 'set -e; rm -f -- "$1"'
    assert cmd[3:] == ["sh", "/var/tmp/x", "second"]


def test_system_path_excludes_usr_local_and_empty_components() -> None:
    components = SYSTEM_PATH.split(":")
    assert components == ["/usr/sbin", "/usr/bin", "/sbin", "/bin"]
    assert "" not in components


def test_pinned_env_overrides_a_caller_path_and_keeps_the_rest() -> None:
    assert pinned_env(None) == {"PATH": SYSTEM_PATH}
    assert pinned_env({"PATH": "/home/agent/.local/bin", "RESTIC_PASSWORD": "pw"}) == {
        "RESTIC_PASSWORD": "pw",
        "PATH": SYSTEM_PATH,
    }


@pytest.mark.skipif(os.name != "posix", reason="needs a POSIX sh")
def test_scripts_are_valid_posix_sh() -> None:
    for argv in (pinned_command(["x"]), pinned_shell_command("echo hi")):
        subprocess.run(["sh", "-n", "-c", argv[2]], check=True)


async def test_privileged_exec_forwards_every_argument_with_pinned_path() -> None:
    sandbox = CannedSandbox.returning(OK)
    await privileged_exec(
        sandbox,
        ["test", "-e", "/root/.cache/x"],
        user="root",
        input=b"stdin",
        cwd="/work",
        env={"A": "b", "PATH": "/evil"},
        timeout=5,
    )
    [(cmd, user)] = sandbox.exec_calls
    assert cmd == pinned_command(["test", "-e", "/root/.cache/x"])
    assert user == "root"
    assert sandbox.inputs == [b"stdin"]
    assert sandbox.envs == [{"A": "b", "PATH": SYSTEM_PATH}]


async def test_privileged_shell_forwards_every_argument_with_pinned_path() -> None:
    sandbox = CannedSandbox.returning(OK)
    await privileged_shell(
        sandbox, 'cat > "$1"', "/root/file", user=None, input="data", env={"A": "b"}
    )
    [(cmd, user)] = sandbox.exec_calls
    assert cmd == pinned_shell_command('cat > "$1"', "/root/file")
    assert user is None
    assert sandbox.inputs == ["data"]
    assert sandbox.envs == [{"A": "b", "PATH": SYSTEM_PATH}]


# ---------------------------------------------------------------------------
# Run for real against a simulated image environment (LocalSandboxEnvironment)
# ---------------------------------------------------------------------------


@pytest.fixture
def local() -> Iterator[LocalSandboxEnvironment]:
    if os.name != "posix" or not Path(SHELL_PATH).exists():
        pytest.skip("requires a POSIX host with /bin/sh")
    sandbox = LocalSandboxEnvironment()
    yield sandbox
    sandbox.directory.cleanup()


class ForgedImage:
    """A directory of forged utilities and the log each one appends to when run."""

    def __init__(self, root: Path, names: list[str]) -> None:
        self.bindir = root / "forged-bin"
        self.bindir.mkdir()
        self.log = root / "forged.log"
        for name in names:
            shim = self.bindir / name
            shim.write_text(f"#!/bin/sh\necho forged-{name} >> {self.log}\nexit 99\n")
            shim.chmod(0o755)

    @property
    def path(self) -> str:
        """An image ``PATH`` with the forged directory first and an empty component."""
        return f"{self.bindir}::{os.environ['PATH']}"

    def ran(self) -> list[str]:
        return self.log.read_text().split() if self.log.exists() else []


@pytest.fixture
def forged(tmp_path: Path) -> ForgedImage:
    return ForgedImage(
        tmp_path, ["sh", "rm", "mkdir", "tar", "test", "stat", "id", "chmod", "cat"]
    )


class _ImageEnvSandbox(SandboxEnvironment):
    """Runs commands on a local sandbox under a simulated image environment.

    ``image_env`` stands in for the container's configured environment (its
    ``PATH`` above all). With ``honours_env`` the caller's ``env`` overrides it,
    as ``docker exec --env`` does; without it the caller's ``env`` is dropped, as
    a provider that cannot set environment variables would.
    """

    def __init__(
        self,
        inner: SandboxEnvironment,
        image_env: dict[str, str],
        *,
        honours_env: bool,
    ) -> None:
        super().__init__()
        self.inner = inner
        self.image_env = image_env
        self.honours_env = honours_env

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
        merged = (
            {**self.image_env, **(env or {})} if self.honours_env else self.image_env
        )
        return await self.inner.exec(cmd, input, cwd, merged, None, timeout)

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


async def test_control_a_bare_shell_runs_the_forgery(
    local: LocalSandboxEnvironment, forged: ForgedImage
) -> None:
    """The fixture works: a provider resolving ``sh`` via the image PATH runs the forgery."""
    sandbox = _ImageEnvSandbox(local, {"PATH": forged.path}, honours_env=True)
    result = await sandbox.exec(["sh", "-c", "true"])
    assert result.returncode == 99
    assert forged.ran() == ["forged-sh"]


@pytest.mark.parametrize("honours_env", [True, False], ids=["env", "no-env"])
async def test_privileged_exec_ignores_forged_utilities(
    local: LocalSandboxEnvironment,
    forged: ForgedImage,
    tmp_path: Path,
    honours_env: bool,
) -> None:
    sandbox = _ImageEnvSandbox(local, {"PATH": forged.path}, honours_env=honours_env)
    victim = tmp_path / "victim"
    victim.write_text("x")

    result = await privileged_exec(sandbox, ["rm", "-f", "--", str(victim)], user=None)

    assert result.success, result.stderr
    assert not victim.exists()
    assert forged.ran() == []


@pytest.mark.parametrize("honours_env", [True, False], ids=["env", "no-env"])
async def test_privileged_shell_ignores_forged_utilities_and_nested_sh(
    local: LocalSandboxEnvironment,
    forged: ForgedImage,
    tmp_path: Path,
    honours_env: bool,
) -> None:
    sandbox = _ImageEnvSandbox(local, {"PATH": forged.path}, honours_env=honours_env)
    made = tmp_path / "made"

    result = await privileged_shell(
        sandbox,
        # A nested bare `sh` inside the script must also resolve through the pin.
        'mkdir -p -- "$1" && tar --version >/dev/null && sh -c \'printf %s "$PATH"\'',
        str(made),
        user=None,
    )

    assert result.success, result.stderr
    assert result.stdout == SYSTEM_PATH
    assert made.is_dir()
    assert forged.ran() == []


async def test_privileged_exec_passes_stdin_and_exit_status_through(
    local: LocalSandboxEnvironment,
) -> None:
    result = await privileged_exec(
        local, ["sh", "-c", "cat; exit 7"], input="from stdin", user=None
    )
    assert result.returncode == 7
    assert result.stdout == "from stdin"


async def test_privileged_exec_honours_cwd(
    local: LocalSandboxEnvironment, tmp_path: Path
) -> None:
    result = await privileged_exec(local, ["pwd"], cwd=str(tmp_path), user=None)
    assert result.success
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


async def test_privileged_exec_reports_a_utility_missing_from_system_dirs(
    local: LocalSandboxEnvironment, tmp_path: Path
) -> None:
    """A utility only on the inherited PATH is not found, rather than run from there."""
    forged = ForgedImage(tmp_path, ["frobnicate"])
    sandbox = _ImageEnvSandbox(local, {"PATH": forged.path}, honours_env=True)
    result = await privileged_exec(sandbox, ["frobnicate"], user=None)
    assert not result.success
    assert result.returncode == 127
    assert "not found" in result.stderr
    assert forged.ran() == []


# ---------------------------------------------------------------------------
# Mechanical guard over src: framework commands never pass a literal argv to exec
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[3] / "src" / "inspect_ai"

_LITERAL_ARGV_ALLOWED = {
    # Agent-facing tools: the command is the agent's own, runs with the agent's
    # authority, and must see the image's PATH as the agent would.
    "tool/_tools/_execute.py",
    "tool/_tools/_read_file.py",
    # The deprecated dedicated web-browser image: a single-purpose container with
    # no agent boundary, whose `python3` lives in /usr/local/bin.
    "tool/_tools/_web_browser/_back_compat.py",
    # The provider conformance checks exercise a provider's own resolution of
    # `sh` and of root commands on purpose; they are not framework operations.
    "util/_sandbox/self_check.py",
}


def _literal_argv(call: ast.Call) -> ast.List | None:
    """The argv of an ``exec`` call when it is written as a list literal."""
    argv = call.args[0] if call.args else None
    if argv is None:
        argv = next((kw.value for kw in call.keywords if kw.arg == "cmd"), None)
    return argv if isinstance(argv, ast.List) and argv.elts else None


def test_framework_exec_calls_never_pass_a_literal_argv() -> None:
    """Every ``exec`` in ``src`` outside the agent-facing tools goes through the helpers.

    A literal argv (``["sh", "-c", ...]``, ``["rm", ...]``, even ``["/bin/sh",
    "-c", script]`` with an unpinned script) is resolved by the provider through
    the image's PATH, whatever user it runs as, and the sandbox default user is
    root in most images. ``privileged_exec``/``privileged_shell`` (or the
    ``pinned_*`` builders) are ``Call`` nodes, so anything they build passes; an
    argv whose first element is a name such as ``SHELL_PATH`` or ``SANDBOX_CLI``
    passes too, and reviewers must check that its script pins ``PATH`` itself.
    """
    assert _SRC.is_dir(), _SRC
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if "ts-mono" in rel or rel in _LITERAL_ARGV_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "exec"
            ):
                continue
            argv = _literal_argv(node)
            if argv is None:
                continue
            first = argv.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.append(f"{rel}:{node.lineno}: {ast.unparse(argv)[:70]}")
    assert offenders == []


def test_guard_catches_the_shapes_it_is_for() -> None:
    """The guard's detector flags positional, keyword, and absolute-shell argvs."""
    source = (
        'await sb.exec(["sh", "-c", "x"], user="root")\n'
        'await sb.exec(cmd=["bash", "-c", "x"])\n'
        'await sb.exec(["/bin/sh", "-c", "x"])\n'
        'await sb.exec(["rm", "-f", "x"])\n'
        'await sb.exec([SHELL_PATH, "-c", SCRIPT])\n'
        'await sb.exec(pinned_command(["rm", "x"]))\n'
    )
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exec"
    ]
    assert len(calls) == 6
    flagged = [
        ast.unparse(argv.elts[0])
        for call in calls
        if (argv := _literal_argv(call)) is not None
        and isinstance(argv.elts[0], ast.Constant)
    ]
    assert flagged == ["'sh'", "'bash'", "'/bin/sh'", "'rm'"]


# ---------------------------------------------------------------------------
# Docker acceptance: an image with forged utilities first on PATH
# ---------------------------------------------------------------------------

_FORGED_COMPOSE = str(Path(__file__).parent / "docker_forged_path" / "compose.yaml")
_FORGED_LOG = "/tmp/forged.log"


@pytest.fixture
async def forged_docker_environment(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DockerSandboxEnvironment]:
    task_name = f"{__name__}_{request.node.name}"
    await DockerSandboxEnvironment.task_init(
        task_name=task_name, config=_FORGED_COMPOSE
    )
    environments = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=_FORGED_COMPOSE, metadata={}
    )
    try:
        yield environments["default"].as_type(DockerSandboxEnvironment)
    finally:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name,
            config=_FORGED_COMPOSE,
            environments=environments,
            interrupted=False,
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=_FORGED_COMPOSE, cleanup=True
        )


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX paths in the fixture")
async def test_docker_privileged_commands_ignore_forged_utilities(
    forged_docker_environment: DockerSandboxEnvironment,
) -> None:
    """No host-issued privileged command runs a utility from the image's PATH.

    The image puts a non-root-owned directory of forged ``sh``, ``tar``, ``rm``,
    ``timeout`` (and so on) ahead of the system directories. The control shows
    Docker does resolve a bare ``sh`` there even for ``--user root``; everything
    Inspect itself issues afterwards must leave the forgery log empty.
    """
    env = forged_docker_environment

    control = await env.exec(["sh", "-c", "true"], user="root")
    assert control.returncode == 99, control
    assert "forged-sh" in await env.read_file(_FORGED_LOG)

    # Clearing the log is itself a root command; the forged `rm` must not run.
    cleared = await privileged_exec(env, ["rm", "-f", _FORGED_LOG], user="root")
    assert cleared.success, cleared.stderr

    # Timed root commands go through the provider's `timeout` wrapper too.
    made = await privileged_exec(
        env, ["mkdir", "-p", "/root/pinned-check"], user="root", timeout=30
    )
    assert made.success, made.stderr
    shell = await privileged_shell(
        env,
        'tar --version >/dev/null && rm -rf /root/pinned-check && printf %s "$PATH"',
        user="root",
        timeout=30,
    )
    assert shell.success, shell.stderr
    assert shell.stdout == SYSTEM_PATH

    # The framework-directory helper (tools and human-agent installs).
    await ensure_framework_directory(
        env, "/var/tmp/.forged-check", user="root", expected_uid=0
    )
    wrapped = await exec_in_framework_directory(
        env,
        "/var/tmp/.forged-check",
        ["sh", "-c", "tar --version >/dev/null && cat > ./ok"],
        user="root",
        expected_uid=0,
        input=b"ok",
    )
    assert wrapped.success, wrapped.stderr

    # The provider's own file write runs as the default user.
    await env.write_file("/tmp/forged-check.txt", "written")
    assert await env.read_file("/tmp/forged-check.txt") == "written"
    await env.write_file("/tmp/forged-check.bin", b"\x00\x01")
    assert await env.read_file("/tmp/forged-check.bin", text=False) == b"\x00\x01"

    ran = await privileged_exec(env, ["test", "-e", _FORGED_LOG], user="root")
    assert not ran.success, await env.read_file(_FORGED_LOG)
