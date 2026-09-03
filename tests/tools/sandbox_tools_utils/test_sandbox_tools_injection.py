"""Tests for sandbox tools injection."""

from contextlib import asynccontextmanager
from io import BytesIO
from typing import AsyncIterator, BinaryIO, NamedTuple

import pytest
from test_helpers.sandbox import CannedSandbox

from inspect_ai.event._sandbox import SandboxEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.tool._sandbox_tools_utils import sandbox as sandbox_tools
from inspect_ai.util._sandbox._cli import SANDBOX_CLI, SANDBOX_TOOLS_DIR
from inspect_ai.util._sandbox._framework_directory import (
    _MISSING_MARKER,
    _STAT_ENTRY,
    _UNAVAILABLE_MARKER,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    SHELL_PATH,
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
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
    return cmd[:2] == [SHELL_PATH, "-c"] and SANDBOX_TOOLS_DIR.rsplit("/", 1)[1] in cmd


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
    mode: str


def helper_flags(cmd: list[str]) -> HelperFlags:
    assert is_framework_dir_call(cmd)
    leaf = SANDBOX_TOOLS_DIR.rsplit("/", 1)[1]
    return HelperFlags(*cmd[cmd.index(leaf) - 5 : cmd.index(leaf) - 1])


def helper_ok(cmd: list[str], user: str | None) -> ExecResult[str]:
    """Every helper call verifies; every other command succeeds."""
    return VERIFIED if is_framework_dir_call(cmd) else OK


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

    sandbox = CannedSandbox(policy)
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

    sandbox = CannedSandbox(policy)
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

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert stub_artifact["extracted_as"] is None


async def test_inject_uses_root_and_verifies_before_start(
    stub_artifact: dict[str, object],
) -> None:
    sandbox = CannedSandbox(helper_ok)
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
    # The tools tree stays private to the tools user.
    assert all(flags.mode == "700" for flags in root_flags)
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

    sandbox = CannedSandbox(policy)
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

    sandbox = CannedSandbox(policy)
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

    sandbox = CannedSandbox(policy)
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

    sandbox = CannedSandbox(policy)
    with pytest.raises(sandbox_tools.SandboxInjectionError, match=expected):
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert stub_artifact["extracted"] is True
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


async def test_extract_runs_tar_inside_verified_directory() -> None:
    sandbox = CannedSandbox(helper_ok)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")

    (tar_cmd, user), (rm_cmd, rm_user) = sandbox.exec_calls
    assert user == "root"
    assert wrapped_command(tar_cmd) == ["tar", "xzf", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"]
    assert "-C" not in tar_cmd
    # Cleanup also goes through the helper (pinned PATH), never a bare-name rm as root.
    assert rm_user == "root"
    assert wrapped_command(rm_cmd) == ["rm", "-f", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"]


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

    sandbox = CannedSandbox(policy)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", None)

    tar_calls = [
        wrapped_command(cmd)
        for cmd, _ in sandbox.exec_calls
        if is_framework_dir_call(cmd) and wrapped_command(cmd)[:1] == ["tar"]
    ]
    assert tar_calls == [
        ["tar", "xzf", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"],
        ["tar", "xf", f"{SANDBOX_TOOLS_DIR}.pkg.tar"],
    ]


async def test_extract_propagates_tar_failure_and_removes_archive() -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_framework_dir_call(cmd) and wrapped_command(cmd)[:1] == ["tar"]:
            return violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(FrameworkDirectoryError, match="is a symbolic link"):
        await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")
    # The staged archive is not left behind in the world-writable parent.
    assert [
        wrapped_command(cmd)
        for cmd, user in sandbox.exec_calls
        if is_framework_dir_call(cmd) and user == "root"
    ][-1] == ["rm", "-f", f"{SANDBOX_TOOLS_DIR}.pkg.tgz"]
    assert not any(cmd[:1] == ["rm"] for cmd, _ in sandbox.exec_calls)


async def test_extract_cleanup_verdict_does_not_mask_original_error() -> None:
    """If the directory is untrusted, the rm is skipped rather than raising over tar's error."""
    sandbox = CannedSandbox(
        lambda cmd, user: violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
    )
    with pytest.raises(FrameworkDirectoryError, match="is a symbolic link"):
        await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")
    assert not any(cmd[:1] == ["rm"] for cmd, _ in sandbox.exec_calls)


async def test_detector_checks_as_known_tools_user() -> None:
    sandbox = CannedSandbox(lambda cmd, user: REGULAR_FILE)
    sandbox._tools_user = "root"
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    # Checked as the tools user, inside the verified directory, by relative name.
    [(cmd, user)] = sandbox.exec_calls
    assert user == "root"
    assert wrapped_command(cmd) == [
        "sh",
        "-c",
        _STAT_ENTRY,
        "sh",
        "inspect-sandbox-tools",
    ]


@pytest.mark.parametrize(
    "stdout, expected",
    [
        pytest.param("81ed\n", True, id="regular-0755"),
        pytest.param("8180\n", True, id="regular-0600"),
        pytest.param("a1ff\n", False, id="symlink"),
        pytest.param("41ed\n", False, id="directory"),
        pytest.param("missing\n", False, id="missing"),
    ],
)
async def test_detector_reads_launcher_type_from_raw_mode(
    stdout: str, expected: bool
) -> None:
    """Only a regular file at the launcher name counts as installed."""
    sandbox = CannedSandbox(
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

    sandbox = CannedSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user == "root"


async def test_detector_pins_default_user_after_definitive_uid_mismatch() -> None:
    """A provider that ran us as non-root will keep doing so: remember it."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        return NOT_ROOT if user == "root" else REGULAR_FILE

    sandbox = CannedSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert [user for _, user in sandbox.exec_calls] == ["root", None]

    # The adopted rootless install is remembered: no repeated root probe.
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == ["root", None, None]


@pytest.mark.parametrize(
    "root_failure",
    [
        pytest.param(
            RuntimeError("runuser: may not be used by non-root users"),
            id="provider-raises",
        ),
        pytest.param(NO_ROOT, id="provider-fails-with-status"),
    ],
)
async def test_detector_does_not_pin_default_user_after_ambiguous_root_failure(
    root_failure: Exception | ExecResult[str],
) -> None:
    """An exception or exit status may be transient: use the install, don't pin it."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            if isinstance(root_failure, Exception):
                raise root_failure
            return root_failure
        return REGULAR_FILE

    sandbox = CannedSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is False
    assert [user for _, user in sandbox.exec_calls] == ["root", None]

    # Next call probes root again rather than trusting the earlier fallback.
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == ["root", None, "root", None]


async def test_transient_root_failure_cannot_pin_a_planted_tree(
    stub_artifact: dict[str, object],
) -> None:
    """A planted tree survives one transient root failure, not the sample.

    Root-capable sandbox: the agent plants a 0700 tree under its own uid and the
    first root probe fails transiently. The planted tree serves that one call, but
    the next call's root probe sees it as a violation and injection fails loud
    instead of the tree being adopted for the rest of the sample.
    """
    calls = {"root": 0}

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root" and is_framework_dir_call(cmd):
            calls["root"] += 1
            if calls["root"] == 1:
                raise RuntimeError("docker exec: transient failure")
            return violation(
                f"{SANDBOX_TOOLS_DIR} is owned by uid 1111, expected uid 0"
            )
        return REGULAR_FILE if is_framework_dir_call(cmd) else OK

    sandbox = CannedSandbox(policy)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user_resolved is False

    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    with pytest.raises(
        sandbox_tools.SandboxInjectionError, match="owned by uid 1111, expected uid 0"
    ):
        await sandbox_tools._inject_container_tools_code(sandbox)
    assert stub_artifact["extracted"] is False
    assert sandbox._tools_user is None
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


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
                success=True,
                returncode=0,
                stdout="missing\n",
                stderr=f"{_VERIFIED_MARKER}\n",
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
    sandbox = CannedSandbox(lambda cmd, user: result)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    # Root worked (the check ran), so the default user's view is irrelevant.
    assert [user for _, user in sandbox.exec_calls] == ["root"]
    assert sandbox._tools_user is None


async def test_detector_treats_provider_exception_as_not_installed() -> None:
    def raising(cmd: list[str], user: str | None) -> ExecResult[str]:
        raise ConnectionError("sandbox gone")

    assert await sandbox_tools._sandbox_tools_installed(CannedSandbox(raising)) is False


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\nstat: cannot statx 'inspect-sandbox-tools': Input/output error\n",
            ),
            id="stat-fails",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="regular file\n",
                stderr=f"{_VERIFIED_MARKER}\n",
            ),
            id="stat-prints-no-mode",
        ),
    ],
)
async def test_detector_treats_unreadable_launcher_as_not_installed(
    result: ExecResult[str],
) -> None:
    """A launcher whose type cannot be read counts as not installed, as before.

    ``stat_in_framework_directory`` raises here where the old inline ``stat`` made
    the check return False; the detector's broad catch keeps the outcome the same
    (injection re-extracts) and the tools user is not pinned by the failure.
    """
    sandbox = CannedSandbox(lambda cmd, user: result)
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is False

    # Same verdict once the tools user is already known.
    sandbox._tools_user = "root"
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False


async def test_detector_records_no_transcript_events() -> None:
    """The per-tool-call probe must not add its script to the transcript each time."""
    transcript = Transcript()
    init_transcript(transcript)
    inner = CannedSandbox(lambda cmd, user: REGULAR_FILE)
    proxy = SandboxEnvironmentProxy(inner)

    assert await sandbox_tools._sandbox_tools_installed(proxy) is True
    assert inner.exec_calls, "the probe must still run"
    assert [e for e in transcript.events if isinstance(e, SandboxEvent)] == []
    # Event recording is back on for whatever the tool runs next.
    await proxy.exec(["echo", "hi"])
    [event] = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    assert event.cmd == "echo hi"
