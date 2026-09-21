"""Tests for sandbox tools injection."""

import os
import sys
import warnings
from contextlib import asynccontextmanager
from io import BytesIO
from typing import AsyncIterator, BinaryIO, Iterator

import anyio
import pytest
from test_helpers.sandbox import (
    ROOT_AMBIGUOUS,
    ROOT_UNUSABLE,
    ROOT_USABLE,
    CannedSandbox,
    ExecPolicy,
    FrameworkDirectoryCall,
    framework_directory_call,
    is_root_probe,
    root_probe_result,
)

from inspect_ai._util import logger as inspect_logger
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
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox._privileged import SHELL_PATH, SYSTEM_PATH
from inspect_ai.util._sandbox.context import init_sandbox_environments_sample
from inspect_ai.util._sandbox.environment import (
    RootAccess,
    SandboxDefaultUser,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxUnavailableError,
)
from inspect_ai.util._sandbox.events import (
    SandboxEnvironmentProxy,
    SandboxTimeoutError,
)
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


def _tools_dir_call(cmd: list[str]) -> FrameworkDirectoryCall | None:
    call = framework_directory_call(cmd)
    return call if call is not None and call.path == SANDBOX_TOOLS_DIR else None


def is_framework_dir_call(cmd: list[str]) -> bool:
    return _tools_dir_call(cmd) is not None


def wrapped_command(cmd: list[str]) -> list[str]:
    """The command a framework-directory call execs after verification."""
    call = _tools_dir_call(cmd)
    assert call is not None
    return list(call.cmd)


def helper_flags(cmd: list[str]) -> FrameworkDirectoryCall:
    """The fixed arguments a framework-directory call passes ahead of the path."""
    call = _tools_dir_call(cmd)
    assert call is not None
    return call


DEFAULT_USER = ExecResult(
    success=True,
    returncode=0,
    stdout="Uid: 1111\t1111\t1111\t1111\nGid: 1111\t1111\t1111\t1111\nGroups: 1111 \nHOME: /home/nonroot\nHOME_SET: 1\n",
    stderr="",
)
"""Result of the default-user identity probe (compose `user: nonroot`)."""
NONROOT = SandboxDefaultUser(uid=1111, gid=1111, groups=[1111], home="/home/nonroot")


def is_identity_probe(cmd: list[str]) -> bool:
    return cmd[:2] == ["/bin/sh", "-c"] and "Groups:" in cmd[2]


TAR_XZF_STDIN = "tar xzf - || { cat >/dev/null; exit 1; }"
TAR_XF_STDIN = "tar xf - || { cat >/dev/null; exit 1; }"


def helper_ok(cmd: list[str], user: str | None) -> ExecResult[str]:
    """Every helper call verifies; every other command succeeds (root is usable)."""
    if is_framework_dir_call(cmd):
        return VERIFIED
    if is_identity_probe(cmd):
        return DEFAULT_USER
    if is_root_probe(cmd):
        return root_probe_result()
    return OK


@pytest.fixture
def _warn_once_messages() -> Iterator[list[str]]:
    # warn_once dedupes via a module-level list; clear it and yield it so the test
    # can assert on what was emitted (caplog is unreliable once an earlier test has
    # set propagate=False on the inspect_ai logger).
    inspect_logger._warned.clear()
    yield inspect_logger._warned
    inspect_logger._warned.clear()


def root_access_warned(messages: list[str]) -> bool:
    return sandbox_tools._AMBIGUOUS_ROOT_ACCESS_WARNING in messages


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
async def test_inject_falls_back_with_warning_when_root_probe_gives_no_verdict(
    stub_artifact: dict[str, object],
    _warn_once_messages: list[str],
    root_failure: Exception | ExecResult[str],
) -> None:
    """With no recorded decision the probe runs on first use; no verdict warns.

    A probe with no verdict still selects the default user, but with a warning.
    """

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            if isinstance(root_failure, Exception):
                raise root_failure
            return root_failure
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "ambiguous"
    assert sandbox._tools_user is None
    assert sandbox._tools_default_user is None
    assert stub_artifact["extracted_as"] is None
    # Root was probed exactly once, and never with a bare mkdir.
    root_calls = [cmd for cmd, user in sandbox.exec_calls if user == "root"]
    assert len(root_calls) == 1 and is_root_probe(root_calls[0])
    assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls
    assert root_access_warned(_warn_once_messages)


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


async def test_root_access_is_probed_once_on_first_use_without_sample_init() -> None:
    """With no recorded decision the first detection probes, records, and adopts."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_identity_probe(cmd):
            return DEFAULT_USER
        return REGULAR_FILE if is_framework_dir_call(cmd) else root_probe_result()

    sandbox = CannedSandbox(policy)
    assert sandbox._root_access is None
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "usable"
    assert sandbox._tools_user == "root"
    assert sum(is_root_probe(cmd) for cmd, _ in sandbox.exec_calls) == 1

    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sum(is_root_probe(cmd) for cmd, _ in sandbox.exec_calls) == 1


@pytest.mark.parametrize(
    "root_failure, expected",
    [
        pytest.param(
            RuntimeError("docker exec: transient failure"),
            "transient failure",
            id="provider-raises",
        ),
        pytest.param(
            NO_ROOT, "no matching entries in passwd", id="provider-fails-with-status"
        ),
        pytest.param(
            NOT_ROOT, "did not run as the requested user", id="provider-runs-other-uid"
        ),
    ],
)
async def test_inject_errors_on_root_failure_after_usable_verdict(
    stub_artifact: dict[str, object],
    _warn_once_messages: list[str],
    root_failure: Exception | ExecResult[str],
    expected: str,
) -> None:
    """Once root is known usable, a root failure is an error, never a rootless install."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            if isinstance(root_failure, Exception):
                raise root_failure
            return root_failure
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_USABLE
    with pytest.raises(sandbox_tools.SandboxInjectionError, match=expected):
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is False
    assert stub_artifact["extracted"] is False
    assert not any(
        user is None and is_framework_dir_call(cmd) for cmd, user in sandbox.exec_calls
    )
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)
    assert _warn_once_messages == []


async def test_inject_installs_rootless_quietly_when_root_unusable(
    stub_artifact: dict[str, object], _warn_once_messages: list[str]
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        assert user is None, "no root exec at all once root is known unusable"
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_UNUSABLE
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert stub_artifact["extracted_as"] is None
    assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls
    assert not any(is_root_probe(cmd) for cmd, _ in sandbox.exec_calls)
    assert _warn_once_messages == []


async def test_inject_warns_once_per_process_when_root_access_ambiguous(
    stub_artifact: dict[str, object], _warn_once_messages: list[str]
) -> None:
    """An ambiguous decision installs as the default user, warned once, not per sandbox."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        assert user is None, "an ambiguous decision must not probe root again"
        return helper_ok(cmd, user)

    for _ in range(2):
        sandbox = CannedSandbox(policy)
        sandbox._root_access = ROOT_AMBIGUOUS
        await sandbox_tools._inject_container_tools_code(sandbox)
        assert sandbox._tools_user is None
        assert sandbox._tools_user_resolved is True
        assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls

    assert _warn_once_messages == [sandbox_tools._AMBIGUOUS_ROOT_ACCESS_WARNING]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            SandboxUnavailableError("container is not running"), id="unavailable"
        ),
        pytest.param(TimeoutError("root probe timed out"), id="timeout"),
    ],
)
async def test_tools_surface_a_failed_probe_instead_of_falling_back(
    stub_artifact: dict[str, object], _warn_once_messages: list[str], error: Exception
) -> None:
    """A probe that could not run decided nothing: the tools refuse to pick a user."""
    sandbox = CannedSandbox(helper_ok)
    sandbox._root_access = RootAccess(
        "failed", f"root probe did not complete: {error}", error
    )

    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    with pytest.raises(
        sandbox_tools.SandboxInjectionError, match="root probe did not complete"
    ) as excinfo:
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert str(error) in str(excinfo.value)
    assert excinfo.value.cause is error and excinfo.value.__cause__ is error
    assert sandbox.exec_calls == []
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is False
    assert stub_artifact["extracted"] is False
    assert _warn_once_messages == []


async def test_exec_remote_surfaces_failed_probe_without_marking_tools_injected() -> (
    None
):
    sandbox = CannedSandbox(helper_ok)
    sandbox._root_access = RootAccess(
        "failed", "root probe did not complete", SandboxUnavailableError("gone")
    )
    with pytest.raises(sandbox_tools.SandboxInjectionError):
        await sandbox.exec_remote(["true"], stream=False)
    assert sandbox._tools_injected is False
    assert sandbox.exec_calls == []


async def test_inject_uses_root_and_verifies_before_start(
    stub_artifact: dict[str, object],
) -> None:
    sandbox = CannedSandbox(helper_ok)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._tools_user == "root"
    assert sandbox._tools_default_user == NONROOT
    assert [u for cmd, u in sandbox.exec_calls if is_identity_probe(cmd)] == [None]
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
    assert not helper_flags(sandbox.exec_calls[start - 1][0]).create
    # Every root-side check insists the script really ran as uid 0, and none asks
    # for a wrong-mode root-owned directory to be repaired.
    root_flags = [
        helper_flags(cmd)
        for cmd, user in sandbox.exec_calls
        if is_framework_dir_call(cmd) and user == "root"
    ]
    assert all(flags.expected_uid == "0" for flags in root_flags)
    assert not any(flags.repair for flags in root_flags)
    # The tools tree stays private to the tools user.
    assert all(flags.mode == "700" for flags in root_flags)
    # No path-based chmod: the directory is created 0700 and verified, not repaired.
    assert not any(cmd[:1] == ["chmod"] for cmd, _ in sandbox.exec_calls)


async def test_inject_falls_back_when_provider_runs_root_as_default_user(
    stub_artifact: dict[str, object], _warn_once_messages: list[str]
) -> None:
    """A provider that ignores `user` must yield a rootless install, not a fake root one.

    The probe itself runs as the default user then, which is a definitive verdict:
    no warning, and root is never asked for again.
    """

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_root_probe(cmd):
            return root_probe_result(uid="1000")
        assert user is None, "root must not be used once the probe ran as another uid"
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "unusable"
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert stub_artifact["extracted_as"] is None
    assert ([SANDBOX_CLI, "start-server"], None) in sandbox.exec_calls
    assert _warn_once_messages == []
    # Default-user checks carry no uid expectation (the host cannot know it). Only
    # the install step repairs a wrong-mode directory the default user owns; the
    # detector and the pre-launch re-check never do.
    default_flags = [
        helper_flags(cmd)
        for cmd, user in sandbox.exec_calls
        if is_framework_dir_call(cmd) and user is None
    ]
    assert all(flags.expected_uid == "" for flags in default_flags)
    assert [flags.repair for flags in default_flags if flags.create] == [True]
    assert not any(flags.repair for flags in default_flags if not flags.create)


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
        if is_framework_dir_call(cmd):
            return violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
        return OK

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_UNUSABLE
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
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    with pytest.raises(sandbox_tools.SandboxInjectionError, match=expected):
        await sandbox_tools._inject_container_tools_code(sandbox)

    assert stub_artifact["extracted"] is True
    assert not any(cmd[:1] == [SANDBOX_CLI] for cmd, _ in sandbox.exec_calls)


async def test_inject_names_a_message_less_exception(
    stub_artifact: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken stdin write raises with no message; the error still says what happened."""

    async def broken_extract(*_args: object) -> None:
        raise anyio.BrokenResourceError()

    monkeypatch.setattr(sandbox_tools, "_extract_tools_tree", broken_extract)
    with pytest.raises(
        sandbox_tools.SandboxInjectionError, match="BrokenResourceError"
    ):
        await sandbox_tools._inject_container_tools_code(CannedSandbox(helper_ok))


async def test_extract_streams_archive_to_tar_inside_verified_directory() -> None:
    sandbox = CannedSandbox(helper_ok)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")

    [(tar_cmd, user)] = sandbox.exec_calls
    assert user == "root"
    assert wrapped_command(tar_cmd) == ["sh", "-c", TAR_XZF_STDIN]
    assert sandbox.inputs == [b"gz"]
    assert sandbox.written == []


async def test_extract_falls_back_to_plain_tar_inside_verified_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sandbox_tools, "_uncompressed_tar_bytes", lambda name, gz: b"tar"
    )

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_framework_dir_call(cmd) and TAR_XZF_STDIN in cmd:
            return ExecResult(
                success=False,
                returncode=2,
                stdout="",
                stderr=f"{_VERIFIED_MARKER}\ntar: gzip: not found\n",
            )
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", None)

    assert [wrapped_command(cmd) for cmd, _ in sandbox.exec_calls] == [
        ["sh", "-c", TAR_XZF_STDIN],
        ["sh", "-c", TAR_XF_STDIN],
    ]
    assert sandbox.inputs == [b"gz", b"tar"]
    assert sandbox.written == []


async def test_extract_propagates_helper_verdict() -> None:
    sandbox = CannedSandbox(
        lambda cmd, user: violation(f"{SANDBOX_TOOLS_DIR} is a symbolic link")
    )
    with pytest.raises(FrameworkDirectoryError, match="is a symbolic link"):
        await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")
    assert len(sandbox.exec_calls) == 1
    assert sandbox.written == []


async def test_extract_reports_failure_of_both_tar_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sandbox_tools, "_uncompressed_tar_bytes", lambda name, gz: b"tar"
    )
    sandbox = CannedSandbox.returning(
        ExecResult(
            success=False,
            returncode=2,
            stdout="",
            stderr=f"{_VERIFIED_MARKER}\ntar: short read\n",
        )
    )
    with pytest.raises(RuntimeError, match="Failed to extract sandbox tools"):
        await sandbox_tools._extract_tools_tree(sandbox, "name", b"gz", "root")
    assert len(sandbox.exec_calls) == 2


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
        if is_identity_probe(cmd):
            return DEFAULT_USER
        assert user == "root", "default user must not be consulted when root works"
        return REGULAR_FILE

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_USABLE
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user == "root"
    assert sandbox._tools_default_user == NONROOT


async def test_detector_adopts_default_user_install_when_root_unusable(
    _warn_once_messages: list[str],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        assert user is None, "root must never be consulted once known unusable"
        return REGULAR_FILE

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_UNUSABLE
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True
    assert [user for _, user in sandbox.exec_calls] == [None]

    # The adopted rootless install is remembered.
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == [None, None]
    assert _warn_once_messages == []


async def test_detector_adopts_default_user_install_with_warning_when_ambiguous(
    _warn_once_messages: list[str],
) -> None:
    """An ambiguous decision is applied like "unusable", plus the warning.

    Root is not probed again either.
    """
    sandbox = CannedSandbox(lambda cmd, user: REGULAR_FILE)
    sandbox._root_access = ROOT_AMBIGUOUS
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is True

    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert [user for _, user in sandbox.exec_calls] == [None, None]
    assert _warn_once_messages == [sandbox_tools._AMBIGUOUS_ROOT_ACCESS_WARNING]


async def test_detector_does_not_warn_for_an_ambiguous_sandbox_it_only_visits(
    _warn_once_messages: list[str],
) -> None:
    """Detection alone records no user, so a sandbox with no install is not warned."""
    sandbox = CannedSandbox(lambda cmd, user: MISSING)
    sandbox._root_access = ROOT_AMBIGUOUS
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    assert sandbox._tools_user_resolved is False
    assert _warn_once_messages == []


async def test_root_failure_after_usable_verdict_never_consults_default_user(
    stub_artifact: dict[str, object],
) -> None:
    """A planted tree is never looked at once root is known usable.

    Root-capable sandbox: the agent plants a 0700 tree under its own uid and root
    then fails transiently. Detection reports "not installed" without consulting
    the default user's view, and the injection that follows fails loud on the
    planted tree instead of installing as that uid.
    """
    calls = {"root": 0}

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if user == "root":
            calls["root"] += 1
            if calls["root"] == 1:
                raise RuntimeError("docker exec: transient failure")
            return violation(
                f"{SANDBOX_TOOLS_DIR} is owned by uid 1111, expected uid 0"
            )
        return REGULAR_FILE if is_framework_dir_call(cmd) else helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_USABLE
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    assert [user for _, user in sandbox.exec_calls] == ["root"]

    with pytest.raises(
        sandbox_tools.SandboxInjectionError, match="owned by uid 1111, expected uid 0"
    ):
        await sandbox_tools._inject_container_tools_code(sandbox)
    assert stub_artifact["extracted"] is False
    assert sandbox._tools_user is None
    assert not any(
        user is None and is_framework_dir_call(cmd) for cmd, user in sandbox.exec_calls
    )
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
    sandbox._root_access = ROOT_USABLE
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    # Root is usable, so the default user's view is never consulted.
    assert [user for _, user in sandbox.exec_calls] == ["root"]
    assert sandbox._tools_user is None


async def test_detector_treats_provider_exception_as_not_installed() -> None:
    def raising(cmd: list[str], user: str | None) -> ExecResult[str]:
        raise ConnectionError("sandbox gone")

    sandbox = CannedSandbox(raising)
    sandbox._root_access = ROOT_USABLE
    assert await sandbox_tools._sandbox_tools_installed(sandbox) is False
    assert [user for _, user in sandbox.exec_calls] == ["root"]


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
    sandbox._root_access = ROOT_USABLE
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
    inner = CannedSandbox(
        lambda cmd, user: DEFAULT_USER if is_identity_probe(cmd) else REGULAR_FILE
    )
    proxy = SandboxEnvironmentProxy(inner)
    proxy._root_access = ROOT_USABLE

    assert await sandbox_tools._sandbox_tools_installed(proxy) is True
    assert inner.exec_calls, "the probe must still run"
    assert [e for e in transcript.events if isinstance(e, SandboxEvent)] == []
    # Event recording is back on for whatever the tool runs next.
    await proxy.exec(["echo", "hi"])
    [event] = [e for e in transcript.events if isinstance(e, SandboxEvent)]
    assert event.cmd == "echo hi"


@pytest.mark.parametrize(
    "result",
    [
        ExecResult(success=False, returncode=1, stdout="", stderr="sh: boom"),
        ExecResult(success=True, returncode=0, stdout="garbage", stderr=""),
    ],
)
async def test_inject_fails_when_default_user_unknown(
    stub_artifact: dict[str, object], result: ExecResult[str]
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        return result if is_identity_probe(cmd) else helper_ok(cmd, user)

    with pytest.raises(sandbox_tools.SandboxInjectionError, match="default user"):
        await sandbox_tools._inject_container_tools_code(CannedSandbox(policy))


def test_parse_default_user() -> None:
    parse = sandbox_tools._parse_default_user
    assert parse(
        "Uid: 0\t0\t0\t0\nGid: 0\t0\t0\t0\nGroups: \nHOME: /root\nHOME_SET: 1\n"
    ) == (SandboxDefaultUser(uid=0, gid=0, groups=[], home="/root"))
    assert parse(
        "Uid: 1000 1000 1000 1000\nGid: 5 5 5 5\nGroups: 4 20 1000\nHOME: /\nHOME_SET: 1\n"
    ) == (SandboxDefaultUser(uid=1000, gid=5, groups=[4, 20, 1000], home="/"))
    assert (
        parse("Uid: 5 5 5 5\nGid: 5 5 5 5\nGroups: 5\nHOME: \nHOME_SET: 1\n").home == ""
    )
    assert (
        parse("Uid: 5 5 5 5\nGid: 5 5 5 5\nGroups: 5\nHOME: \nHOME_SET: \n").home
        is None
    )
    # a login banner precedes the probe output and must not shadow it
    assert (
        parse(
            "HOME: /banner\nUid: 5 5 5 5\nGid: 5 5 5 5\nGroups: 5\nHOME: /real\nHOME_SET: 1\n"
        ).home
        == "/real"
    )


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(RuntimeError("docker exec: transient failure"), id="exception"),
        pytest.param(
            ExecResult(success=False, returncode=1, stdout="", stderr="boom"),
            id="failed",
        ),
        pytest.param(
            ExecResult(success=True, returncode=0, stdout="garbage\n", stderr=""),
            id="unparsable",
        ),
    ],
)
async def test_detector_fails_loud_when_identity_probe_fails(
    failure: Exception | ExecResult[str],
) -> None:
    """An unreadable default identity on a healthy root install is an error.

    Not a reinjection; nothing is cached, so the next call retries the probe.
    """
    probes = {"n": 0}

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_identity_probe(cmd):
            probes["n"] += 1
            if probes["n"] == 1:
                if isinstance(failure, Exception):
                    raise failure
                return failure
            return DEFAULT_USER
        return REGULAR_FILE

    sandbox = CannedSandbox(policy)
    sandbox._root_access = ROOT_USABLE
    with pytest.raises(sandbox_tools.SandboxDefaultUserError, match="default user"):
        await sandbox_tools._sandbox_tools_installed(sandbox)
    assert sandbox._tools_user is None
    assert sandbox._tools_user_resolved is False
    assert sandbox._tools_default_user is None

    assert await sandbox_tools._sandbox_tools_installed(sandbox) is True
    assert sandbox._tools_user == "root"
    assert sandbox._tools_default_user == NONROOT


@pytest.mark.parametrize(
    "probe",
    [
        pytest.param(root_probe_result("0000000000000000"), id="cap_drop-all"),
        pytest.param(root_probe_result("0000000000000040"), id="setgid-without-setuid"),
        pytest.param(root_probe_result(setgroups="deny"), id="setgroups-denied"),
        pytest.param(root_probe_result(uid="1000"), id="not-root"),
    ],
)
async def test_inject_falls_back_quietly_when_root_cannot_switch_users(
    stub_artifact: dict[str, object],
    _warn_once_messages: list[str],
    probe: ExecResult[str],
) -> None:
    """Root that cannot switch identity is a definitive verdict: rootless, no warning."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        return probe if is_root_probe(cmd) else helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "unusable"
    assert sandbox._tools_user is None
    assert sandbox._tools_default_user is None
    assert stub_artifact["extracted_as"] is None
    assert not any(
        is_framework_dir_call(cmd) and user == "root"
        for cmd, user in sandbox.exec_calls
    )
    assert _warn_once_messages == []


@pytest.mark.parametrize(
    "probe",
    [
        pytest.param(
            ExecResult(success=False, returncode=1, stdout="", stderr="exec failed"),
            id="probe-failed",
        ),
        pytest.param(
            ExecResult(success=True, returncode=0, stdout="allow\n", stderr=""),
            id="probe-output-short",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="Welcome: to the VM\nUid: 0 0 0 0\nCapEff: 000001ffffffffff\n",
                stderr="",
            ),
            id="probe-missing-key-with-noise",
        ),
        pytest.param(root_probe_result("not-hex"), id="probe-unparsable"),
    ],
)
async def test_inject_falls_back_with_warning_when_probe_output_has_no_verdict(
    stub_artifact: dict[str, object],
    _warn_once_messages: list[str],
    probe: ExecResult[str],
) -> None:
    """Probe output that cannot be read as a verdict is ambiguous, not "no root"."""

    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        return probe if is_root_probe(cmd) else helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)

    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "ambiguous"
    assert "KeyError" not in sandbox._root_access.reason
    assert sandbox._tools_user is None
    assert stub_artifact["extracted_as"] is None
    assert root_access_warned(_warn_once_messages)


async def test_root_probe_tolerates_login_shell_noise(
    stub_artifact: dict[str, object],
) -> None:
    def policy(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_root_probe(cmd):
            return root_probe_result(noise="Welcome to the VM\n")
        return helper_ok(cmd, user)

    sandbox = CannedSandbox(policy)
    await sandbox_tools._inject_container_tools_code(sandbox)
    assert sandbox._root_access is not None
    assert sandbox._root_access.state == "usable"
    assert sandbox._tools_user == "root"


# ---------------------------------------------------------------------------
# The root-access decision itself: probe, verdict, recording at sample init
# ---------------------------------------------------------------------------


async def test_probe_runs_the_fixed_script_as_root_with_pinned_path() -> None:
    sandbox = CannedSandbox.returning(root_probe_result())
    access = await sandbox_tools._probe_root_access(sandbox)

    assert access.state == "usable"
    [(cmd, user)] = sandbox.exec_calls
    assert user == "root"
    assert cmd[:2] == [SHELL_PATH, "-c"] and is_root_probe(cmd)
    assert sandbox.envs == [{"PATH": SYSTEM_PATH}]


async def test_probe_is_bounded_by_the_provider_timeout_without_retry() -> None:
    """The probe hands the provider its timeout and asks for no retry.

    A provider timeout excludes time spent queued behind other sandbox commands on
    a busy host, which a deadline around the whole exec would count.
    """
    sandbox = CannedSandbox.returning(root_probe_result())
    await sandbox_tools._probe_root_access(sandbox)
    assert sandbox.timeouts == [(sandbox_tools._ROOT_ACCESS_PROBE_TIMEOUT, False)]


@pytest.mark.parametrize(
    "probe, state, reason",
    [
        pytest.param(root_probe_result(), "usable", "can switch users", id="usable"),
        pytest.param(
            root_probe_result(noise="Welcome: to the VM\n"),
            "usable",
            "can switch users",
            id="usable-despite-login-banner",
        ),
        pytest.param(
            root_probe_result(uid="1000"),
            "unusable",
            "run as uid 1000",
            id="runs-as-another-uid",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout=root_probe_result(uid="1000").stdout,
                stderr="",
            ),
            "unusable",
            "run as uid 1000",
            id="verdict-despite-failing-status",
        ),
        pytest.param(
            root_probe_result("0000000000000000"),
            "unusable",
            "cannot switch users",
            id="cap_drop-all",
        ),
        pytest.param(
            root_probe_result("0000000000000040"),
            "unusable",
            "cannot switch users",
            id="setgid-without-setuid",
        ),
        pytest.param(
            root_probe_result(setgroups="deny"),
            "unusable",
            "setgroups deny",
            id="setgroups-denied",
        ),
        pytest.param(NO_ROOT, "ambiguous", "exit status 126", id="status-no-output"),
        pytest.param(
            ExecResult(
                success=True, returncode=0, stdout="setgroups: allow\n", stderr=""
            ),
            "ambiguous",
            "no verdict",
            id="fields-missing",
        ),
        pytest.param(
            root_probe_result("not-hex"),
            "ambiguous",
            "could not be parsed",
            id="unparsable-caps",
        ),
        pytest.param(
            root_probe_result(uid="garbled"),
            "ambiguous",
            "could not be parsed",
            id="unparsable-uid",
        ),
        pytest.param(
            root_probe_result(setgroups="garbled"),
            "ambiguous",
            "could not be parsed",
            id="unparsable-setgroups",
        ),
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="Uid:\nCapEff: 000001ffffffffff\nsetgroups: allow\n",
                stderr="",
            ),
            "ambiguous",
            "could not be parsed",
            id="empty-uid",
        ),
    ],
)
async def test_probe_verdict(probe: ExecResult[str], state: str, reason: str) -> None:
    access = await sandbox_tools._probe_root_access(CannedSandbox.returning(probe))
    assert access.state == state
    assert reason in access.reason
    assert access.error is None


@pytest.mark.parametrize(
    "error, state",
    [
        pytest.param(
            RuntimeError("runuser: may not be used by non-root users"),
            "ambiguous",
            id="provider-raises",
        ),
        pytest.param(ConnectionError("sandbox gone"), "ambiguous", id="other-error"),
        pytest.param(
            SandboxUnavailableError("container is not running"),
            "failed",
            id="unavailable",
        ),
        pytest.param(TimeoutError("exec timed out"), "failed", id="timeout"),
        pytest.param(
            SandboxTimeoutError("exec timed out"), "failed", id="sandbox-timeout"
        ),
    ],
)
async def test_probe_exception(error: Exception, state: str) -> None:
    def raising(cmd: list[str], user: str | None) -> ExecResult[str]:
        raise error

    access = await sandbox_tools._probe_root_access(CannedSandbox(raising))
    assert access.state == state
    assert access.error is error
    assert str(error) in access.reason


async def test_probe_cancellation_propagates_and_records_nothing() -> None:
    started = anyio.Event()

    class BlockingSandbox(CannedSandbox):
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
            started.set()
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

    sandbox = BlockingSandbox(lambda cmd, user: OK)
    async with anyio.create_task_group() as tg:
        tg.start_soon(sandbox_tools.resolve_root_access, sandbox)
        await started.wait()
        tg.cancel_scope.cancel()
    assert sandbox._root_access is None


async def test_local_sandbox_is_probed_as_the_current_user_without_warning() -> None:
    """`local` ignores `user` (and warns when given one): its own identity decides.

    The raw provider object is used, as a script outside an eval would: it must
    carry the decision itself, and its proxy is unwrapped for the same treatment.
    """
    local = LocalSandboxEnvironment()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            access = await sandbox_tools.resolve_root_access(local)
    finally:
        local.directory.cleanup()

    assert local._root_access is access
    assert sandbox_tools._root_probe_user(SandboxEnvironmentProxy(local)) is None
    assert not [w for w in caught if issubclass(w.category, UserWarning)], caught
    if sys.platform == "linux":
        assert access.state == ("usable" if os.geteuid() == 0 else "unusable")
    else:
        # no /proc, so the probe reports no identity
        assert access.state == "ambiguous"


async def test_resolve_records_once_and_never_probes_again() -> None:
    sandbox = CannedSandbox.returning(root_probe_result(uid="1000"))
    first = await sandbox_tools.resolve_root_access(sandbox)
    assert first.state == "unusable"
    assert sandbox._root_access is first
    assert await sandbox_tools.resolve_root_access(sandbox) is first
    assert len(sandbox.exec_calls) == 1

    # A recorded decision is returned as is, a failed probe included.
    failed = RootAccess("failed", "did not complete", TimeoutError())
    recorded = CannedSandbox.returning(root_probe_result())
    recorded._root_access = failed
    assert await sandbox_tools.resolve_root_access(recorded) is failed
    assert recorded.exec_calls == []


async def test_resolve_shares_the_decision_between_proxy_and_provider_object() -> None:
    """Whichever of the two views is probed first decides for both.

    `as_type()` returns the object behind the proxy, and a provider may hand out
    one object under several names.
    """
    inner = CannedSandbox.returning(root_probe_result())
    proxy = SandboxEnvironmentProxy(inner)
    access = await sandbox_tools.resolve_root_access(proxy)
    assert proxy._root_access is access
    assert inner._root_access is access
    assert await sandbox_tools.resolve_root_access(inner) is access
    # A second proxy over the same object adopts the decision without probing.
    assert (
        await sandbox_tools.resolve_root_access(SandboxEnvironmentProxy(inner))
        is access
    )
    assert len(inner.exec_calls) == 1

    # And a proxy over an object that already carries one adopts it.
    recorded = CannedSandbox.returning(root_probe_result())
    recorded._root_access = ROOT_UNUSABLE
    assert (
        await sandbox_tools.resolve_root_access(SandboxEnvironmentProxy(recorded))
        is ROOT_UNUSABLE
    )
    assert recorded.exec_calls == []


async def test_resolve_tolerates_a_provider_that_skips_the_base_init() -> None:
    """Several providers (k8s among them) never call `SandboxEnvironment.__init__`."""

    class BareSandbox(CannedSandbox):
        def __init__(self) -> None:
            self.policy = lambda cmd, user: root_probe_result()
            self.exec_calls = []
            self.inputs = []
            self.envs = []
            self.concurrency = []
            self.timeouts = []
            self.written = []

    inner = BareSandbox()
    access = await sandbox_tools.resolve_root_access(SandboxEnvironmentProxy(inner))
    assert access.state == "usable"
    assert inner._root_access is access
    assert await sandbox_tools.resolve_root_access(inner) is access


def provider(**policies: ExecPolicy) -> type[SandboxEnvironment]:
    """A sandbox provider whose sample holds one canned sandbox per policy."""

    class Provider(CannedSandbox):
        @classmethod
        async def sample_init(
            cls,
            task_name: str,
            config: SandboxEnvironmentConfigType | None,
            metadata: dict[str, str],
        ) -> dict[str, SandboxEnvironment]:
            return {name: cls(policy) for name, policy in policies.items()}

    return Provider


async def test_sample_init_records_root_access_for_every_sandbox_last(
    _warn_once_messages: list[str],
) -> None:
    """Every sandbox is probed once at the end of sample init and only recorded.

    The probe runs after the sample files and the setup script, so it is the last
    thing that happens before the solver, and no outcome (a failing probe, no
    verdict) fails or warns at this point; the sandbox tools act on it later.
    """

    def usable(cmd: list[str], user: str | None) -> ExecResult[str]:
        return root_probe_result() if is_root_probe(cmd) else OK

    def no_verdict(cmd: list[str], user: str | None) -> ExecResult[str]:
        return NO_ROOT if is_root_probe(cmd) else OK

    def unavailable(cmd: list[str], user: str | None) -> ExecResult[str]:
        if is_root_probe(cmd):
            raise SandboxUnavailableError("container is not running")
        return OK

    transcript = Transcript()
    init_transcript(transcript)
    environments = await init_sandbox_environments_sample(
        provider(default=usable, other=no_verdict, broken=unavailable),
        "task",
        None,
        files={"a.txt": b"a"},
        setup=b"#!/bin/sh\necho hi\n",
        metadata={},
    )

    states = {
        name: env._root_access.state if env._root_access is not None else None
        for name, env in environments.items()
    }
    assert states == {"default": "usable", "other": "ambiguous", "broken": "failed"}
    assert _warn_once_messages == []

    # Files and the setup script (chmod, run, rm) precede the probe on the default
    # sandbox; the others see nothing but their probe.
    default = environments["default"].as_type(CannedSandbox)
    assert default.written[0] == "a.txt" and len(default.written) == 2
    assert len(default.exec_calls) == 4
    last_cmd, last_user = default.exec_calls[-1]
    assert last_user == "root" and is_root_probe(last_cmd)
    for name in ("other", "broken"):
        [(cmd, user)] = environments[name].as_type(CannedSandbox).exec_calls
        assert user == "root" and is_root_probe(cmd)

    # The decision sits on the recording proxy and on the provider object behind
    # it, which `as_type()` hands out. Each probe whose exec returned is one
    # transcript event, the audit record of the verdict (the proxy records nothing
    # for an exec that raised).
    for env in environments.values():
        assert isinstance(env, SandboxEnvironmentProxy)
        assert env.as_type(CannedSandbox)._root_access is env._root_access
    probe_events = [
        e
        for e in transcript.events
        if isinstance(e, SandboxEvent) and (e.options or {}).get("user") == "root"
    ]
    assert len(probe_events) == 2
