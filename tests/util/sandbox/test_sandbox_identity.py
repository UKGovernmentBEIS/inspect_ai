"""The sandbox identity scope: resolution, default sandbox and injection target."""

import os
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, TypeVar, cast, overload

import anyio
import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.util import (
    SandboxEnvironment,
    SandboxUserUnsupportedError,
    sandbox,
    sandbox_default,
)
from inspect_ai.util._sandbox._framework_operation import framework_sandbox_operation
from inspect_ai.util._sandbox._privileged import pinned_shell_command
from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_default_context_var,
    sandbox_environments_context_var,
    sandbox_file_detector,
    sandbox_with_injection,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.identity import (
    SandboxIdentityError,
    sandbox_identity,
    sandbox_identity_active,
    sandbox_identity_cwd,
    sandbox_identity_user,
    sandbox_identity_vars,
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


def test_the_provider_behind_a_sample_proxy_is_the_same_sandbox(
    default: CannedSandbox, workspace: CannedSandbox
) -> None:
    from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
    from inspect_ai.util._sandbox.identity import sandbox_identity_environment

    proxy = SandboxEnvironmentProxy(default)
    with _environments(default=proxy, workspace=SandboxEnvironmentProxy(workspace)):
        with sandbox_identity("w-1", cwd="/home/w-1"):
            for view in (proxy, default):
                assert sandbox_identity_user(view, None, strict=True) == "w-1"
                with pytest.raises(SandboxIdentityError, match="'root'"):
                    sandbox_identity_user(view, "root", strict=True)
                assert sandbox_identity_cwd(view, None) == "/home/w-1"
                assert sandbox_identity_active(view)
            assert sandbox_identity_user(workspace, None, strict=True) is None
            assert not sandbox_identity_active(workspace)
            assert sandbox_identity_environment() is proxy
        with sandbox_identity("w-1", sandbox="workspace"):
            assert sandbox_identity_user(default, "root", strict=True) == "root"
            assert sandbox_identity_cwd(default, None) is None


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


@pytest.mark.parametrize("user", ["w1:1000", "1000:1000"])
def test_user_with_a_group_raises(default: CannedSandbox, user: str) -> None:
    with _environments(default=default):
        with pytest.raises(ValueError, match="a username or a numeric uid"):
            with sandbox_identity(user):
                pass
        assert not sandbox_identity_active()


def test_relative_cwd_raises(default: CannedSandbox) -> None:
    with _environments(default=default):
        with pytest.raises(ValueError, match="requires an absolute cwd"):
            with sandbox_identity("w-1", cwd="work"):
                pass
        assert not sandbox_identity_active()


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


class _FileSandbox(CannedSandbox):
    """Records `(operation, user)` for every exec, read and write."""

    def __init__(self) -> None:
        super().__init__(lambda _cmd, _user: OK)
        self.calls: list[tuple[str, str | None]] = []

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
        self.calls.append(("exec", user))
        return await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        self.calls.append(("write_file", user))

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
        self.calls.append(("read_file", user))
        return "" if text else b""


def _without_file_users(
    provider: _FileSandbox, monkeypatch: pytest.MonkeyPatch
) -> _FileSandbox:
    """Give `provider` a `read_file()` and `write_file()` that declare no `user`."""

    async def write_file(file: str, contents: str | bytes) -> None:
        provider.calls.append(("write_file", None))

    async def read_file(file: str, text: bool = True) -> str | bytes:
        provider.calls.append(("read_file", None))
        return "" if text else b""

    monkeypatch.setattr(provider, "write_file", write_file)
    monkeypatch.setattr(provider, "read_file", read_file)
    return provider


async def _operations(env: SandboxEnvironment, user: str | None = None) -> None:
    await env.exec(["true"], user=user)
    await env.read_file("f", user=user)
    await env.write_file("f", "x", user=user)


def _sandbox_events(transcript: Transcript) -> list[tuple[str, str | None]]:
    events = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    return [(e.action, cast(str | None, (e.options or {}).get("user"))) for e in events]


OPERATIONS = ["exec", "read_file", "write_file"]


async def test_operations_take_the_scope_user() -> None:
    provider = _FileSandbox()
    transcript = Transcript()
    init_transcript(transcript)
    with _environments(default=SandboxEnvironmentProxy(provider)):
        with sandbox_identity("w-1"):
            await _operations(sandbox())
    assert provider.calls == [(op, "w-1") for op in OPERATIONS]
    assert _sandbox_events(transcript) == [(op, "w-1") for op in OPERATIONS]


async def test_explicit_user_is_kept_in_a_scope() -> None:
    provider = _FileSandbox()
    with _environments(default=SandboxEnvironmentProxy(provider)):
        with sandbox_identity("w-1"):
            await _operations(sandbox(), user="root")
    assert provider.calls == [(op, "root") for op in OPERATIONS]


async def test_other_sandbox_and_outside_scope_unchanged() -> None:
    default, workspace = _FileSandbox(), _FileSandbox()
    proxy = SandboxEnvironmentProxy(default)
    with _environments(default=proxy, workspace=SandboxEnvironmentProxy(workspace)):
        await _operations(proxy)
        with sandbox_identity("w-1", sandbox="workspace"):
            await _operations(proxy)
    assert default.calls == [(op, None) for op in OPERATIONS] * 2
    assert workspace.calls == []


async def test_as_type_view_skips_the_default() -> None:
    provider = _FileSandbox()
    with _environments(default=SandboxEnvironmentProxy(provider)):
        with sandbox_identity("w-1"):
            await _operations(sandbox().as_type(_FileSandbox))
    assert provider.calls == [(op, None) for op in OPERATIONS]


async def test_framework_operation_keeps_the_default_user() -> None:
    provider = _FileSandbox()
    proxy = SandboxEnvironmentProxy(provider)
    started_inside = anyio.Event()

    async def exec_later(started: anyio.Event) -> None:
        await started.wait()
        await proxy.exec(["true"])

    with _environments(default=proxy), sandbox_identity("w-1"):
        with framework_sandbox_operation():
            await _operations(proxy)
            async with anyio.create_task_group() as tg:
                tg.start_soon(exec_later, started_inside)
                started_inside.set()
        await _operations(proxy)
        started_after = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(exec_later, started_after)
            started_after.set()
    assert provider.calls == [
        *[(op, None) for op in OPERATIONS],
        ("exec", None),
        *[(op, "w-1") for op in OPERATIONS],
        ("exec", "w-1"),
    ]


_UNSUPPORTED = (
    r"_FileSandbox\.%s_file does not support a user, so it cannot run as 'w-1' "
    "inside the sandbox identity scope for sandbox 'default'"
)


async def test_provider_without_file_user_raises_in_a_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _without_file_users(_FileSandbox(), monkeypatch)
    proxy = SandboxEnvironmentProxy(provider)
    with _environments(default=proxy):
        await _operations(proxy)
        with sandbox_identity("w-1"):
            with pytest.raises(
                SandboxUserUnsupportedError, match=_UNSUPPORTED % "read"
            ):
                await proxy.read_file("f")
            with pytest.raises(
                SandboxUserUnsupportedError, match=_UNSUPPORTED % "write"
            ):
                await proxy.write_file("f", "x")
            with framework_sandbox_operation():
                await _operations(proxy)
            # exec() takes a user on every provider
            await proxy.exec(["true"])
    assert provider.calls == [
        *[(op, None) for op in OPERATIONS] * 2,
        ("exec", "w-1"),
    ]


async def test_scope_cannot_open_inside_a_framework_operation() -> None:
    # in practice a scorer opening a scope during in-loop scoring
    with _environments(default=SandboxEnvironmentProxy(_FileSandbox())):
        with framework_sandbox_operation():
            with pytest.raises(SandboxIdentityError, match="cannot be opened inside"):
                with sandbox_identity("judge"):
                    pass
        assert not sandbox_identity_active()
        with sandbox_identity("judge"):
            assert sandbox_identity_active()


async def test_file_detection_reads_as_the_default_user_in_a_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `test -r` fails, so detection falls back to reading the file, on a
    # provider whose read_file() cannot take a user
    provider = _without_file_users(_FileSandbox(), monkeypatch)
    provider.policy = lambda _cmd, _user: ExecResult(False, 1, "", "")
    proxy = SandboxEnvironmentProxy(provider)
    with _environments(default=proxy), sandbox_identity("w-1"):
        assert await sandbox_file_detector("/opt/tool")(proxy)
    assert provider.calls == [("exec", None), ("read_file", None)]


async def test_path_detection_runs_as_the_default_user_in_a_scope() -> None:
    provider = _FileSandbox()
    proxy = SandboxEnvironmentProxy(provider)
    with _environments(default=proxy), sandbox_identity("w-1"):
        assert await sandbox_file_detector("python3", on_path=True)(proxy)
    assert provider.calls == [("exec", None)]


def test_framework_operation_marker_sites() -> None:
    """Tripwire: sandbox operations keep the default user only at these sites.

    Inside a `sandbox_identity()` scope, the marker makes an omitted user mean
    the sandbox's default user, so it must never wrap model-chosen work. If this
    fails, route the new code through a marked helper or extend the allowlist
    deliberately (and the list in design/sandbox-trust-model.md).
    """
    src = Path(__file__).parent.parent.parent.parent / "src" / "inspect_ai"
    allowed = {
        src / "util" / "_sandbox" / "_framework_operation.py",  # the marker
        src / "util" / "_sandbox" / "identity.py",  # reads it
        src / "util" / "_sandbox" / "_privileged.py",
        src / "util" / "_sandbox" / "_framework_directory.py",
        src / "util" / "_sandbox" / "_json_rpc_transport.py",
        src / "util" / "_sandbox" / "context.py",
        src / "util" / "_checkpoint" / "_copy.py",
        src / "tool" / "_sandbox_tools_utils" / "sandbox.py",
        src / "scorer" / "_score.py",
        src / "tool" / "_tools" / "_skill" / "install.py",
    }
    users = {
        f
        for f in src.rglob("*.py")
        if "_framework_operation" in f.read_text(encoding="utf-8")
    }
    assert users == allowed


async def test_vars_have_no_home_without_a_passwd_entry(
    default: CannedSandbox,
) -> None:
    # `default` prints nothing for the lookup, as for a user with no entry
    with _environments(default=default), sandbox_identity("w-1"):
        assert await sandbox_identity_vars(default, None) is None
        assert await sandbox_identity_vars(default, None) is None
    [(lookup, user)] = default.exec_calls
    assert (lookup[-1], user) == ("w-1", None)


async def test_vars_raise_when_the_home_lookup_fails() -> None:
    default = CannedSandbox.returning(ExecResult(False, 126, "", "no shell"))
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match="'w-1': no shell"):
            await sandbox_identity_vars(default, None)


def _run_lookup(
    user: str, getent: str = "", passwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the home lookup script on the host.

    `getent` replaces getent with a shell function; `passwd` makes the script
    read that file instead of /etc/passwd, as on an image without getent.
    """
    from inspect_ai.util._sandbox.identity import _PASSWD_HOME_SCRIPT

    script = _PASSWD_HOME_SCRIPT
    if passwd is not None:
        has_getent = "command -v getent >/dev/null 2>&1"
        assert has_getent in script and "/etc/passwd" in script
        script = script.replace(has_getent, "false").replace("/etc/passwd", str(passwd))
    argv = pinned_shell_command(script, user)
    if getent:
        argv[2] = f"getent() {{ {getent}; }}\n" + argv[2]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
def test_home_lookup_script_reads_the_passwd_database() -> None:
    import pwd

    root_home = pwd.getpwuid(0).pw_dir
    for user in (pwd.getpwuid(0).pw_name, "0"):
        result = _run_lookup(user)
        assert (result.returncode, result.stdout) == (0, f"{root_home}\n"), result
    result = _run_lookup("no-such-user-for-inspect")
    assert (result.returncode, result.stdout) == (0, ""), result


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
@pytest.mark.parametrize(
    "getent, status, stdout",
    [
        ("echo 'w:x:1000:1000:W, Jr:/srv/w:/bin/sh'", 0, "/srv/w\n"),
        ("return 2", 0, ""),
        ("echo database-failed >&2; return 1", 1, ""),
        ("return 3", 1, ""),
        ("echo 'w:x:1000:1000:/srv/w'", 1, ""),
        ("echo 'w:x:1000:1000::/srv/w:/bin/sh:extra'", 1, ""),
        ("return 0", 1, ""),
        ("echo 'w:x:1000:1000:: /srv/w :/bin/sh'", 0, " /srv/w \n"),
        ("echo 'w:x:1000:1000:W::/bin/sh'", 0, "\n"),
    ],
    ids=[
        "entry",
        "no-entry",
        "failed",
        "unsupported",
        "malformed",
        "extra-field",
        "empty",
        "spaces",
        "empty-home",
    ],
)
def test_home_lookup_script_fails_unless_getent_answers(
    getent: str, status: int, stdout: str
) -> None:
    result = _run_lookup("w", getent)
    assert (result.returncode, result.stdout) == (status, stdout), result


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
@pytest.mark.parametrize("newline", ["\n", ""], ids=["terminated", "unterminated"])
def test_home_lookup_script_reads_passwd_without_getent(
    tmp_path: Path, newline: str
) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text(
        "root:x:0:0::/root:/bin/sh\ne:x:1001:1001:::/bin/sh\n"
        "m:x:1002:1002::/srv/m\nx:x:1003:1003::/srv/x:/bin/sh:extra\njunk\n"
        "w:x:1000:1000:: /srv/w :/bin/sh" + newline
    )

    def lookup(user: str) -> tuple[int, str]:
        result = _run_lookup(user, passwd=passwd)
        return result.returncode, result.stdout

    assert lookup("w") == (0, " /srv/w \n")
    assert lookup("1000") == (0, " /srv/w \n")
    assert lookup("root") == (0, "/root\n")
    assert lookup("e") == (0, "\n")
    assert lookup("m") == (1, "")
    assert lookup("1002") == (1, "")
    assert lookup("x") == (1, "")
    assert lookup("1003") == (1, "")
    assert lookup("missing") == (0, "")


async def test_vars_keep_whitespace_in_the_home() -> None:
    sb = CannedSandbox.returning(ExecResult(True, 0, " /srv/w \n", ""))
    with _environments(default=sb), sandbox_identity("w"):
        assert await sandbox_identity_vars(sb, None) == {"HOME": " /srv/w "}


class _LookupSandbox(CannedSandbox):
    """Runs the home lookup on the host with a replaced `getent`; can stall it."""

    def __init__(self, getent: str = "", passwd: Path | None = None) -> None:
        super().__init__(lambda _cmd, _user: OK)
        self.getent = getent
        self.passwd = passwd
        self.stall = False
        self.stalled = anyio.Event()

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
        await super().exec(
            cmd, input, cwd, env, user, timeout, timeout_retry, concurrency
        )
        if self.stall:
            self.stalled.set()
            await anyio.sleep_forever()
        result = _run_lookup(cmd[-1], self.getent, self.passwd)
        return ExecResult(
            result.returncode == 0, result.returncode, result.stdout, result.stderr
        )


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
async def test_vars_raise_when_getent_fails_and_retry_later() -> None:
    default = _LookupSandbox("echo database-failed >&2; return 1")
    with _environments(default=default), sandbox_identity("w-1"):
        with pytest.raises(RuntimeError, match="'w-1': database-failed"):
            await sandbox_identity_vars(default, None)
        default.getent = "echo 'w-1:x:1000:1000::/srv/w-1:/bin/sh'"
        assert await sandbox_identity_vars(default, None) == {"HOME": "/srv/w-1"}
    assert len(default.exec_calls) == 2


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
@pytest.mark.parametrize("source", ["getent", "passwd"])
@pytest.mark.parametrize(
    "record, error",
    [
        ("e:x:1001:1001:::/bin/sh", "empty home directory"),
        ("e:x:1001:1001::/srv/e", "malformed entry"),
        ("e:x:1001:1001::/srv/e:/bin/sh:extra", "malformed entry"),
    ],
    ids=["empty-home", "missing-field", "extra-field"],
)
async def test_vars_raise_on_a_bad_entry_and_retry_later(
    tmp_path: Path, source: str, record: str, error: str
) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text(record + "\n")
    if source == "getent":
        sb = _LookupSandbox(getent=f'grep "^$2:" {passwd} || return 2')
    else:
        sb = _LookupSandbox(passwd=passwd)

    # no entry: HOME is left alone, and that answer is cached
    with _environments(default=sb), sandbox_identity("missing"):
        assert await sandbox_identity_vars(sb, None) is None
        assert await sandbox_identity_vars(sb, None) is None
    assert len(sb.exec_calls) == 1

    # a bad entry raises, is not cached, and is looked up again
    with _environments(default=sb), sandbox_identity("e"):
        with pytest.raises(RuntimeError, match=f"'e': .*{error}"):
            await sandbox_identity_vars(sb, None)
        passwd.write_text("e:x:1001:1001::/srv/e:/bin/sh\n")
        assert await sandbox_identity_vars(sb, None) == {"HOME": "/srv/e"}
    assert len(sb.exec_calls) == 3


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
@pytest.mark.parametrize(
    "before",
    [
        "1000:x:2000:2000::/home/numeric:/bin/sh",
        "#old:x:1000:1000::/home/old:/bin/sh",
        "  #old:x:1000:1000::/home/old:/bin/sh",
        "\t#old:x:1000:1000::/home/old:/bin/sh",
    ],
    ids=["numeric-name", "comment", "indented-comment", "tabbed-comment"],
)
async def test_vars_find_a_bare_uid_by_its_uid_field(
    tmp_path: Path, before: str
) -> None:
    passwd = tmp_path / "passwd"
    passwd.write_text(before + "\nw:x:1000:1000::/home/w:/bin/sh\n")
    sb = _LookupSandbox(passwd=passwd)
    for user in ("1000", "01000"):
        with _environments(default=sb), sandbox_identity(user):
            assert await sandbox_identity_vars(sb, None) == {"HOME": "/home/w"}

    # a uid with no account leaves HOME alone, and that answer is cached
    with _environments(default=sb), sandbox_identity("4242"):
        assert await sandbox_identity_vars(sb, None) is None
        assert await sandbox_identity_vars(sb, None) is None
    assert len(sb.exec_calls) == 3


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
async def test_vars_raise_unless_passwd_is_a_file_and_retry_later(
    tmp_path: Path,
) -> None:
    passwd = tmp_path / "passwd"
    passwd.mkdir()
    sb = _LookupSandbox(passwd=passwd)
    with _environments(default=sb), sandbox_identity("w"):
        with pytest.raises(RuntimeError, match="'w': .*not a readable file"):
            await sandbox_identity_vars(sb, None)
        passwd.rmdir()
        passwd.write_text("w:x:1000:1000::/home/w:/bin/sh\n")
        assert await sandbox_identity_vars(sb, None) == {"HOME": "/home/w"}
    assert len(sb.exec_calls) == 2


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
async def test_lookup_does_not_need_the_provider_default_cwd() -> None:
    from inspect_ai.tool import read_file
    from inspect_ai.util._sandbox.local import LocalSandboxEnvironment

    local = LocalSandboxEnvironment()
    local.directory.cleanup()  # the provider's default cwd no longer exists
    user = str(os.geteuid())
    with _environments(default=local), sandbox_identity(user, cwd="/"):
        assert await read_file()(file_path="/etc/hosts", limit=1)


@pytest.mark.parametrize("timeout, expected", [(None, 30), (5, 5), (60, 30)])
async def test_vars_lookup_is_bounded_by_the_tool_timeout(
    default: CannedSandbox, timeout: int | None, expected: int
) -> None:
    with _environments(default=default), sandbox_identity("w-1"):
        await sandbox_identity_vars(default, timeout)
    assert default.timeouts == [(expected, False)]


async def test_vars_lookup_timeout_is_not_cached() -> None:
    lookups: list[str] = []

    def time_out_once(cmd: list[str], _user: str | None) -> ExecResult[str]:
        lookups.append(cmd[-1])
        if len(lookups) == 1:
            raise TimeoutError("lookup timed out")
        return ExecResult(True, 0, "/srv/w-1\n", "")

    sb = CannedSandbox(time_out_once)
    with _environments(default=sb), sandbox_identity("w-1"):
        with pytest.raises(TimeoutError):
            await sandbox_identity_vars(sb, 1)
        assert await sandbox_identity_vars(sb, 1) == {"HOME": "/srv/w-1"}
    assert lookups == ["w-1", "w-1"]


@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX shell")
async def test_vars_lookup_cancelled_before_it_resolves_runs_again() -> None:
    default = _LookupSandbox("echo 'w-1:x:1000:1000::/srv/w-1:/bin/sh'")
    default.stall = True
    with _environments(default=default), sandbox_identity("w-1"):
        async with anyio.create_task_group() as tg:
            tg.start_soon(sandbox_identity_vars, default, None)
            await default.stalled.wait()
            tg.cancel_scope.cancel()
        default.stall = False
        assert await sandbox_identity_vars(default, None) == {"HOME": "/srv/w-1"}
    assert len(default.exec_calls) == 2


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


_T = TypeVar("_T")


class _MemberEnvironments(dict[str, SandboxEnvironment]):
    """Lists `own` only; `visible` resolve by name, as an inspect_swarm member's do."""

    def __init__(
        self,
        own: Mapping[str, SandboxEnvironment],
        visible: Mapping[str, SandboxEnvironment],
    ) -> None:
        super().__init__(own)
        self._visible = dict(visible)

    @overload
    def get(self, key: str, default: None = None, /) -> SandboxEnvironment | None: ...

    @overload
    def get(self, key: str, default: SandboxEnvironment, /) -> SandboxEnvironment: ...

    @overload
    def get(self, key: str, default: _T, /) -> SandboxEnvironment | _T: ...

    def get(self, key: str, default: object = None, /) -> object:
        return super().get(key, self._visible.get(key, default))

    def __getitem__(self, key: str) -> SandboxEnvironment:
        if super().__contains__(key):
            return super().__getitem__(key)
        return self._visible[key]

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key) or key in self._visible


@pytest.mark.parametrize("by_name", [False, True], ids=["hidden", "by-name"])
async def test_injection_refuses_a_scope_sandbox_the_context_does_not_list(
    default: CannedSandbox, workspace: CannedSandbox, by_name: bool
) -> None:
    installed: set[SandboxEnvironment] = {default, workspace}
    with _environments(default=default, workspace=workspace):
        with sandbox_identity("w-1", sandbox="workspace"):
            member = _MemberEnvironments(
                {"default": default}, {"workspace": workspace} if by_name else {}
            )
            token = sandbox_environments_context_var.set(member)
            try:
                with pytest.raises(SandboxIdentityError, match="sandbox 'workspace'"):
                    await sandbox_with_injection(_injectable(installed))
                # a named sandbox or an explicit target is still injected into
                assert (
                    await sandbox_with_injection(_injectable(installed), target=default)
                    is default
                )
                if by_name:
                    assert (
                        await sandbox_with_injection(
                            _injectable(installed), name="workspace"
                        )
                        is workspace
                    )
            finally:
                sandbox_environments_context_var.reset(token)
            # back in the scope's own context, its sandbox is selected again
            assert await sandbox_with_injection(_injectable(installed)) is workspace
