"""Tests for sandbox tools injection."""

import os
import sys
from contextlib import asynccontextmanager
from io import BytesIO
from typing import AsyncIterator, BinaryIO, Callable, Literal, NamedTuple, overload

import pytest

from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.tool._sandbox_tools_utils import sandbox as sandbox_tools
from inspect_ai.util._sandbox._cli import SANDBOX_CLI, SANDBOX_TOOLS_DIR
from inspect_ai.util._sandbox._framework_directory import (
    _MISSING_MARKER,
    _SHELL,
    _UNAVAILABLE_MARKER,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.recon import Architecture, SupportedContainerOSInfo
from inspect_ai.util._subprocess import ExecResult

OK = ExecResult(success=True, returncode=0, stdout="", stderr="")
"""Result of an ordinary (non-helper) command."""

VERIFIED = ExecResult(
    success=True, returncode=0, stdout="", stderr=f"{_VERIFIED_MARKER}\n"
)
"""Helper result: verification passed and the wrapped command (if any) succeeded."""

REGULAR_FILE = ExecResult(
    success=True,
    returncode=0,
    stdout="81ed\n",  # stat -c %f of a 0755 regular file
    stderr=f"{_VERIFIED_MARKER}\n",
)
"""Helper result for the detector: verified, and the launcher is a regular file."""


def violation(message: str) -> ExecResult[str]:
    return ExecResult(
        success=False,
        returncode=3,
        stdout="",
        stderr=f"{_VIOLATION_MARKER}: {message}\n",
    )


MISSING = ExecResult(
    success=False,
    returncode=4,
    stdout="",
    stderr=f"{_MISSING_MARKER}: {SANDBOX_TOOLS_DIR} does not exist\n",
)
UNAVAILABLE = ExecResult(
    success=False,
    returncode=5,
    stdout="",
    stderr=f"{_UNAVAILABLE_MARKER}: cannot stat parent directory /var/tmp: stat: not found\n",
)
NO_ROOT = ExecResult(
    success=False,
    returncode=126,
    stdout="",
    stderr="unable to find user root: no matching entries in passwd file\n",
)
"""A provider that reports an unusable user through the exit status."""
NOT_ROOT = ExecResult(
    success=False,
    returncode=6,
    stdout="",
    stderr=f"{_USER_MISMATCH_MARKER}: running as uid 1000, expected uid 0\n",
)
"""A provider that accepted user="root" but ran the helper as someone else."""


def is_framework_dir_call(cmd: list[str]) -> bool:
    return cmd[:2] == [_SHELL, "-c"] and SANDBOX_TOOLS_DIR.rsplit("/", 1)[1] in cmd


def wrapped_command(cmd: list[str]) -> list[str]:
    """The command a framework-directory call execs after verification."""
    assert is_framework_dir_call(cmd)
    leaf = SANDBOX_TOOLS_DIR.rsplit("/", 1)[1]
    return cmd[cmd.index(leaf) + 1 :]


class HelperFlags(NamedTuple):
    """The fixed arguments a framework-directory call passes ahead of the path."""

    expected_uid: str
    create: str
    repair: str


def helper_flags(cmd: list[str]) -> HelperFlags:
    assert is_framework_dir_call(cmd)
    leaf = SANDBOX_TOOLS_DIR.rsplit("/", 1)[1]
    return HelperFlags(*cmd[cmd.index(leaf) - 4 : cmd.index(leaf) - 1])


Policy = Callable[[list[str], str | None], ExecResult[str]]


def helper_ok(cmd: list[str], user: str | None) -> ExecResult[str]:
    """Every helper call verifies; every other command succeeds."""
    return VERIFIED if is_framework_dir_call(cmd) else OK


class FakeSandbox(SandboxEnvironment):
    """Sandbox whose exec results are decided by a per-test policy."""

    def __init__(self, policy: Policy) -> None:
        super().__init__()
        self.policy = policy
        self.exec_calls: list[tuple[list[str], str | None]] = []
        self.written: list[str] = []

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
        self.exec_calls.append((cmd, user))
        return self.policy(cmd, user)

    async def write_file(self, file: str, contents: str | bytes) -> None:
        self.written.append(file)

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


@pytest.fixture
def stub_artifact(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub OS detection and artifact lookup; record the user extraction ran as."""
    recorded: dict[str, object] = {"extracted_as": None, "extracted": False}

    async def fake_detect_sandbox_os(
        _sandbox: SandboxEnvironment,
    ) -> SupportedContainerOSInfo:
        return {"architecture": "amd64", "libc": "glibc"}

    @asynccontextmanager
    async def fake_open_executable_for_arch(
        _arch: Architecture,
        _musl: bool,
    ) -> AsyncIterator[tuple[str, BinaryIO]]:
        yield "inspect-sandbox-tools", BytesIO(b"binary")

    async def fake_extract_tools_tree(
        _sandbox: SandboxEnvironment,
        _name: str,
        _gz_bytes: bytes,
        user: str | None,
    ) -> None:
        recorded["extracted"] = True
        recorded["extracted_as"] = user

    monkeypatch.setattr(sandbox_tools, "detect_sandbox_os", fake_detect_sandbox_os)
    monkeypatch.setattr(
        sandbox_tools, "_open_executable_for_arch", fake_open_executable_for_arch
    )
    monkeypatch.setattr(sandbox_tools, "_extract_tools_tree", fake_extract_tools_tree)
    return recorded


async def test_inject_falls_back_to_default_user_when_root_probe_raises(
    stub_artifact: dict[str, object],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            raise RuntimeError("runuser: may not be used by non-root users")
        return helper_ok(cmd, user)

    sandbox = FakeSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert stub_artifact["extracted_as"] is None
    # The root probe went through the verified-directory helper, not a bare mkdir.
    root_calls = [cmd for cmd, user in sandbox.exec_calls if user == "root"]
    assert root_calls and all(is_framework_dir_call(cmd) for cmd in root_calls)
    assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls


async def test_detector_skips_root_probe_after_rootless_injection(
    stub_artifact: dict[str, object],
) -> None:
    """Once a rootless install has run, later tool calls do not re-probe root."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            raise RuntimeError("runuser: may not be used by non-root users")
        return REGULAR_FILE if is_framework_dir_call(cmd) else OK

    sandbox = FakeSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)
    assert sandbox._tools_user is None

    sandbox.exec_calls.clear()
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == [None]


async def test_inject_falls_back_when_root_exec_fails_without_verdict(
    stub_artifact: dict[str, object],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        return NO_ROOT if user == "root" else helper_ok(cmd, user)

    sandbox = FakeSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert stub_artifact["extracted_as"] is None


async def test_inject_uses_root_and_verifies_before_start(
    stub_artifact: dict[str, object],
) -> None:
    sandbox = FakeSandbox(helper_ok)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user == "root"
    assert stub_artifact["extracted_as"] == "root"
    # Verified before extraction and again immediately before the launcher starts,
    # the latter without creating anything.
    start = sandbox.exec_calls.index(([SANDBOX_CLI, "start-server"], "root"))
    verifications = [
        i
        for i, (cmd, user) in enumerate(sandbox.exec_calls)
        if is_framework_dir_call(cmd) and user == "root"
    ]
    assert len(verifications) >= 2
    assert verifications[-1] == start - 1
    assert helper_flags(sandbox.exec_calls[start - 1][0]).create == "0"
    # Every root-side check insists the script really ran as uid 0, and none asks
    # for a wrong-mode root-owned directory to be repaired.
    root_flags = [
        helper_flags(cmd)
        for cmd, user in sandbox.exec_calls
        if is_framework_dir_call(cmd) and user == "root"
    ]
    assert all(flags.expected_uid == "0" for flags in root_flags)
    assert all(flags.repair == "0" for flags in root_flags)
    # No path-based chmod: the directory is created 0700 and verified, not repaired.
    assert not any(cmd[:1] == ["chmod"] for cmd, _ in sandbox.exec_calls)


async def test_inject_falls_back_when_provider_runs_root_as_default_user(
    stub_artifact: dict[str, object],
) -> None:
    """A provider that ignores `user` must yield a rootless install, not a fake root one."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root" and is_framework_dir_call(cmd):
            return NOT_ROOT
        return helper_ok(cmd, user)

    sandbox = FakeSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert stub_artifact["extracted_as"] is None
    assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls
    # Default-user checks carry no uid expectation (the host cannot know it). Only
    # the install step repairs a wrong-mode directory the default user owns; the
    # detector and the pre-launch re-check never do.
    default_flags = [
        helper_flags(cmd)
        for cmd, user in sandbox.exec_calls
        if is_framework_dir_call(cmd) and user is None
    ]
    assert all(flags.expected_uid == "" for flags in default_flags)
    assert [flags.repair for flags in default_flags if flags.create == "1"] == ["1"]
    assert all(flags.repair == "0" for flags in default_flags if flags.create == "0")


@pytest.mark.skipif(sys.platform != "linux", reason="helper script needs GNU stat")
async def test_root_probe_is_false_on_local_sandbox() -> None:
    """LocalSandboxEnvironment ignores `user`, so it must not be recorded as root."""
    if os.getuid() == 0:
        pytest.skip("requires a non-root test user")
    local = LocalSandboxEnvironment()
    try:
        with pytest.warns(UserWarning, match="'user' parameter is ignored"):
            assert await sandbox_tools._create_tools_dir_as_root(local) is False
    finally:
        local.directory.cleanup()


@pytest.mark.parametrize(
    "result, expected",
    [
        pytest.param(
            violation(f"{SANDBOX_TOOLS_DIR} is owned by uid 1111, expected uid 0"),
            "owned by uid 1111, expected uid 0",
            id="planted-directory",
        ),
        pytest.param(UNAVAILABLE, "stat: not found", id="cannot-verify"),
    ],
)
async def test_inject_aborts_on_root_verdict_without_downgrading(
    stub_artifact: dict[str, object], result: ExecResult[str], expected: str
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root" and is_framework_dir_call(cmd):
            return result
        return helper_ok(cmd, user)

    sandbox = FakeSandbox(policy)
    with pytest.raises(sandbox_tools.SandboxInjectionError) as excinfo:
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert expected in str(excinfo.value)
    assert sandbox._tools_user is None
    assert stub_artifact["extracted"] is False
    # Never tried the default user, never started a launcher.
    assert all(user == "root" for _, user in sandbox.exec_calls)
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


async def test_inject_aborts_on_rootless_contract_violation(
    stub_artifact: dict[str, object],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            raise RuntimeError("no root")
        if is_framework_dir_call(cmd):
            return violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
        return OK

    sandbox = FakeSandbox(policy)
    with pytest.raises(sandbox_tools.SandboxInjectionError, match="symbolic link"):
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert stub_artifact["extracted"] is False
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


@pytest.mark.parametrize(
    "result, expected",
    [
        pytest.param(
            violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link"),
            "symbolic link",
            id="swapped-for-symlink",
        ),
        pytest.param(MISSING, "does not exist", id="removed"),
    ],
)
async def test_inject_aborts_when_reverification_before_start_fails(
    stub_artifact: dict[str, object], result: ExecResult[str], expected: str
) -> None:
    calls = {"n": 0}

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_framework_dir_call(cmd):
            calls["n"] += 1
            if calls["n"] == 2:  # between extraction and launch
                return result
            return VERIFIED
        return OK

    sandbox = FakeSandbox(policy)
    with pytest.raises(sandbox_tools.SandboxInjectionError, match=expected):
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert stub_artifact["extracted"] is True
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


async def test_extract_runs_tar_inside_verified_directory() -> None:
    sandbox = FakeSandbox(helper_ok)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")

    (tar_cmd, user), (rm_cmd, _) = sandbox.exec_calls
    assert user == "root"
    assert wrapped_command(tar_cmd) == ["tar", "xzf", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"]
    assert "-C" not in tar_cmd
    assert rm_cmd == ["rm", "-f", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"]


async def test_extract_falls_back_to_plain_tar_inside_verified_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sandbox_tools, "_uncompressed_tar_bytes", lambda name, gz: b"tar"
    )

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_framework_dir_call(cmd) and "xzf" in cmd:
            return ExecResult(
                success=False,
                returncode=2,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\ntar: gzip: not found\n",
            )
        return helper_ok(cmd, user)

    sandbox = FakeSandbox(policy)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", None)

    tar_calls = [
        wrapped_command(cmd)
        for cmd, _ in sandbox.exec_calls
        if is_framework_dir_call(cmd)
    ]
    assert tar_calls == [
        ["tar", "xzf", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"],
        ["tar", "xf", f"{SANDBOX_TOOLS_DIR}.pkg.tar"],
    ]


async def test_extract_propagates_contract_violation_and_removes_archive() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_framework_dir_call(cmd):
            return violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
        return OK

    sandbox = FakeSandbox(policy)
    with pytest.raises(FrameworkDirectoryError, match="is a symbolic link"):
        await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")
    # The staged archive is not left behind in the world-writable parent.
    assert (["rm", "-f", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"], "root") in sandbox.exec_calls


async def test_detector_checks_as_known_tools_user() -> None:
    sandbox = FakeSandbox(lambda cmd, user: REGULAR_FILE)
    sandbox._tools_user = "root"
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    # Checked as the tools user, inside the verified directory, by relative name.
    [(cmd, user)] = sandbox.exec_calls
    assert user == "root"
    assert wrapped_command(cmd) == ["stat", "-c", "%f", "inspect-sandbox-tools"]


@pytest.mark.parametrize(
    "stdout, expected",
    [
        pytest.param("81ed\n", True, id="regular-0755"),
        pytest.param("8180\n", True, id="regular-0600"),
        pytest.param("a1ff\n", False, id="symlink"),
        pytest.param("41ed\n", False, id="directory"),
        pytest.param("regular file\n", False, id="localized-%F-output"),
        pytest.param("", False, id="empty"),
    ],
)
async def test_detector_reads_launcher_type_from_raw_mode(
    stdout: str, expected: bool
) -> None:
    """The launcher check uses the raw st_mode, not the locale-dependent %F text."""
    sandbox = FakeSandbox(
        lambda cmd, user: ExecResult(
            success=True, returncode=0, stdout=stdout, stderr=f"{_VERIFIED_MARKER}\n"
        )
    )
    sandbox._tools_user = "root"
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is expected


async def test_detector_adopts_existing_root_installation() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        assert user == "root", "default user must not be consulted when root works"
        return REGULAR_FILE

    sandbox = FakeSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user == "root"


@pytest.mark.parametrize(
    "root_failure",
    [
        pytest.param(
            RuntimeError("runuser: may not be used by non-root users"),
            id="provider-raises",
        ),
        pytest.param(NO_ROOT, id="provider-fails-with-status"),
        pytest.param(NOT_ROOT, id="provider-runs-as-another-uid"),
    ],
)
async def test_detector_falls_back_to_default_user_when_root_unavailable(
    root_failure: Exception | ExecResult[str],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            if isinstance(root_failure, Exception):
                raise root_failure
            return root_failure
        return REGULAR_FILE

    sandbox = FakeSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert [user for _, user in sandbox.exec_calls] == ["root", None]

    # The adopted rootless install is remembered: no repeated root probe.
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == ["root", None, None]


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            violation(f"{SANDBOX_TOOLS_DIR} is owned by uid 1111, expected uid 0"),
            id="wrong-owner",
        ),
        pytest.param(
            violation(f"{SANDBOX_TOOLS_DIR} has mode 755, expected 700"),
            id="wrong-mode",
        ),
        pytest.param(MISSING, id="not-installed-yet"),
        pytest.param(UNAVAILABLE, id="cannot-verify"),
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\nstat: cannot stat 'inspect-sandbox-tools'\n",
            ),
            id="launcher-missing",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="a1ff\n",  # stat -c %f of a symlink
                stderr=f"{_VERIFIED_MARKER}\n",
            ),
            id="launcher-is-symlink",
        ),
    ],
)
async def test_detector_reports_not_installed_and_does_not_downgrade(
    result: ExecResult[str],
) -> None:
    sandbox = FakeSandbox(lambda cmd, user: result)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    # Root worked (the check ran), so the default user's view is irrelevant.
    assert [user for _, user in sandbox.exec_calls] == ["root"]
    assert sandbox._tools_user is None


async def test_detector_treats_provider_exception_as_not_installed() -> None:
    def raising(cmd: list[str], user: str | None) -> ExecResult[str]:
        raise ConnectionError("sandbox gone")

    assert await sandbox_tools._sandbox_tools_installed(FakeSandbox(raising)) is False


async def test_detector_records_no_transcript_events() -> None:
    """The per-tool-call probe must not add its script to the transcript each time."""
    transcript = Transcript()
    init_transcript(transcript)
    inner = FakeSandbox(lambda cmd, user: REGULAR_FILE)
    proxy = SandboxEnvironmentProxy(inner)

    assert await sandbox_tools._sandbox_tools_installed(proxy) is True
    assert inner.exec_calls, "the probe must still run"
    assert [e for e in transcript.events if isinstance(e, SandboxEvent)] == []
    # Event recording is back on for whatever the tool runs next.
    await proxy.exec(["echo", "hi"])
    [event] = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    assert event.cmd == "echo hi"
