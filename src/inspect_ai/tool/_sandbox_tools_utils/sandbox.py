import gzip
import os
import stat
import subprocess
import sys
import tempfile
import warnings
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from importlib import resources
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Literal, get_args
from urllib.parse import unquote, urlparse

import anyio
import httpx
from rich.prompt import Prompt

import inspect_ai
from inspect_ai._util.download import download
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.package import get_package_direct_url
from inspect_ai._util.trace import trace_message
from inspect_ai.util import input_screen
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._sandbox._cli import (
    SANDBOX_CLI,
    SANDBOX_TOOLS_BASE_NAME,
    SANDBOX_TOOLS_DIR,
)
from inspect_ai.util._sandbox._framework_directory import (
    FrameworkDirectoryError,
    FrameworkDirectoryNotFoundError,
    ensure_framework_directory,
    exec_in_framework_directory,
    expected_uid_for,
    stat_in_framework_directory,
    verify_framework_directory,
)
from inspect_ai.util._sandbox._privileged import privileged_shell
from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_with_injection,
)
from inspect_ai.util._sandbox.environment import (
    RootAccess,
    SandboxDefaultUser,
    SandboxEnvironment,
    SandboxUnavailableError,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.recon import Architecture, detect_sandbox_os
from inspect_ai.util._subprocess import ExecResult

from ._build_config import (
    SandboxToolsBuildConfig,
    config_to_filename,
)
from ._digests import lookup_digest

_BUCKET_BASE_URL = "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com"

logger = getLogger(__name__)


TRACE_SANDBOX_TOOLS = "Sandbox Tools"


class SandboxDefaultUserError(RuntimeError):
    """A trustworthy tools install exists but the default exec identity could not be read."""


class SandboxInjectionError(Exception):
    """Exception raised when sandbox tools injection fails.

    This error wraps any exception that occurs during the injection process
    to provide a clear signal that the failure was specifically during injection.
    This is required because SandboxInjection happens as a side effect of making
    a tool call. We need to make sure that injection errors are not interpreted
    and handled specially (e.g. give to the model) as exceptions throw from tool
    calls are.
    """

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.__cause__ = cause


InstallState = Literal["pypi", "clean", "edited"]
"""Represents the state of the inspect-ai installation.

- **pypi**: PyPI installation
- **clean**: Non-PyPI install with no sandbox tools changes relative to main
- **edited**: Non-PyPI install with changes to sandbox tools
"""


async def sandbox_with_injected_tools(
    *,
    sandbox_name: str | None = None,
    sandbox: SandboxEnvironment | None = None,
) -> SandboxEnvironment:
    """Create a sandbox environment with sandbox tools injection.

    Args:
        sandbox_name: Optional name for the sandbox environment.
        sandbox: Optional sandbox instance to inject into directly.

    Returns:
        A sandbox environment with container tools injected.
    """
    return await sandbox_with_injection(
        SandboxInjectable(
            _sandbox_tools_installed,
            _inject_container_tools_code,
        ),
        name=sandbox_name,
        target=sandbox,
    )


async def _sandbox_tools_installed(sandbox: SandboxEnvironment) -> bool:
    """Detect a trustworthy existing sandbox-tools installation.

    An installation is reused only when ``SANDBOX_TOOLS_DIR`` satisfies the
    framework-directory contract for the tools user and the launcher inside it is a
    regular file. A merely readable launcher is not enough: a tree owned by another
    principal could substitute its own launcher.

    The check runs as the tools user only: the user an injection on this sandbox
    object already recorded, or else the one the sandbox's root-access decision
    selects (see ``_tools_user_for``). A trustworthy installation found that way (a
    fresh object attached to a sandbox that already holds one) is adopted by
    recording that user. The default user's view is never consulted on a sandbox
    whose root is usable: a root exec failure there reads as "not installed", and
    the injection that follows fails loud rather than installing as the default
    user, so a tree the agent planted under its own uid can never be adopted
    because root happened to fail.

    The check records no transcript events: it repeats on every tool call and its
    argv carries the whole verification script, so logging it would add kilobytes
    of identical shell to the transcript per call. The injection and the one-off
    root probe (see ``resolve_root_access``), which each run once per sandbox, are
    still recorded.

    Raises:
        SandboxDefaultUserError: A trustworthy root installation was found but the
            default exec identity could not be read (see the handler below).
    """
    try:
        with _without_sandbox_events(sandbox):
            return await _detect_sandbox_tools(sandbox)
    except SandboxDefaultUserError:
        # The install is healthy, so reinjecting cannot fix this, and running the
        # tools with no identity would misreport as a permission error. Nothing is
        # cached, so the next call retries the probe.
        raise
    except Exception as ex:
        # Broad catch is deliberate: detectors run against every candidate sandbox
        # and providers raise provider-specific types for an unusable one. Treat it
        # as "not installed"; injection then surfaces any real failure.
        trace_message(logger, TRACE_SANDBOX_TOOLS, f"tools detection failed: {ex}")
        return False


async def _detect_sandbox_tools(sandbox: SandboxEnvironment) -> bool:
    if sandbox._tools_user_resolved or sandbox._tools_user is not None:
        return await _tools_installed_as(sandbox, sandbox._tools_user)

    user = await _tools_user_for(sandbox)
    installed = await _tools_installed_as(sandbox, user)
    if installed:
        await _set_tools_user(sandbox, user)
    return installed


async def _tools_user_for(sandbox: SandboxEnvironment) -> str | None:
    """The user the sandbox tools install and run as (``None`` = default user).

    Applies the sandbox's recorded root-access decision (``resolve_root_access``):
    root when usable, otherwise the default user, including when the probe gave no
    verdict, since some providers report "cannot exec as root" only that way (that
    case is warned once the default user is recorded; see ``_set_tools_user``). A
    probe that could not run or did not complete is an error here rather than a
    reason to fall back.
    """
    access = await resolve_root_access(sandbox)
    if access.state == "usable":
        return "root"
    if access.state in ("unusable", "ambiguous"):
        return None
    raise SandboxInjectionError(
        "Failed to inject sandbox tools into sandbox: cannot choose the user for "
        f"the tools because the {access.reason}",
        cause=access.error,
    )


def _without_sandbox_events(
    sandbox: SandboxEnvironment,
) -> AbstractContextManager[None]:
    """Suppress transcript events for commands run on ``sandbox`` inside the block.

    Only the event-recording proxy that wraps sample sandboxes emits events; any
    other sandbox object (a provider used directly, or a test fake) needs nothing.
    """
    if isinstance(sandbox, SandboxEnvironmentProxy):
        return sandbox.no_events()
    return nullcontext()


_AMBIGUOUS_ROOT_ACCESS_WARNING = (
    "Sandbox tools: the sandbox gave no answer to whether it can run commands as "
    "root, so the tools run as the sandbox's default user (the user a sandbox "
    "command runs as when none is given). If root is in fact available there, the "
    "tools are not protected from the code running in the sandbox. Details are in "
    "the trace log under 'Sandbox Tools'."
)


async def _set_tools_user(sandbox: SandboxEnvironment, user: str | None) -> None:
    """Record which user the sandbox tools run as (``None`` = default user).

    With a root tools user, also capture the default exec identity so tool calls
    without an explicit user can run as it (see ``_detect_default_user``). A default
    user chosen because the root probe gave no verdict is warned here, once per
    process: this is where that fallback takes effect, for a sandbox the tools
    actually use, rather than for every sandbox detection merely visits.
    """
    default_user = await _detect_default_user(sandbox) if user == "root" else None
    sandbox._tools_user = user
    sandbox._tools_user_resolved = True
    sandbox._tools_default_user = default_user
    access = sandbox._root_access
    if user is None and access is not None and access.state == "ambiguous":
        warn_once(logger, _AMBIGUOUS_ROOT_ACCESS_WARNING)


async def _tools_installed_as(sandbox: SandboxEnvironment, user: str | None) -> bool:
    """Check for a trustworthy installation from ``user``'s point of view.

    Returns False when the tools directory is missing, violates the contract, or
    does not hold a regular-file launcher (injection then creates it, fails loudly,
    or re-extracts; a symlink at the launcher name reports its own type and is
    rejected). Raises when the check did not run (the provider cannot exec as
    ``user``) or could not be performed.
    """
    try:
        st_mode = await stat_in_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            SANDBOX_TOOLS_BASE_NAME,
            user=user,
            expected_uid=expected_uid_for(user),
        )
    except FrameworkDirectoryNotFoundError:
        return False
    except FrameworkDirectoryError as ex:
        trace_message(logger, TRACE_SANDBOX_TOOLS, f"tools dir not reusable: {ex}")
        return False
    return st_mode is not None and stat.S_ISREG(st_mode)


async def _inject_container_tools_code(sandbox: SandboxEnvironment) -> None:
    try:
        user = await _tools_user_for(sandbox)

        info = await detect_sandbox_os(sandbox)
        musl = info.get("libc") == "musl"

        async with _open_executable_for_arch(info["architecture"], musl) as (name, f):
            gz_bytes = f.read()  # gzipped tar of the PyInstaller --onedir tree

        # Prepare the install dir as the tools user: verified to be a real directory
        # owned by that user with mode 0700 before anything is extracted into it. A
        # root-owned 0700 tree prevents access by other, non-root users, but not by
        # a process running in the sandbox as root; as root nothing is repaired, and
        # a failing root exec here is an error, never a reason to install as the
        # default user instead. In a rootless sandbox the agent shares the tools
        # user's uid, so a directory that uid owns is tightened to 0700 rather than
        # refused: older releases left rootless installs at 0755 (on the host, for
        # the `local` sandbox).
        if user == "root":
            await ensure_framework_directory(
                sandbox, SANDBOX_TOOLS_DIR, user="root", expected_uid=0
            )
        else:
            await ensure_framework_directory(
                sandbox, SANDBOX_TOOLS_DIR, user=None, repair_mode=True
            )
        await _set_tools_user(sandbox, user)

        await _extract_tools_tree(sandbox, name, gz_bytes, user)

        # Re-verify immediately before the launcher runs with the tools user's
        # authority. Extraction targets the verified directory object, so this
        # only fails if the entry at the path was swapped or removed in between.
        await verify_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            user=user,
            expected_uid=expected_uid_for(user),
        )

        # As root the server can setuid to any user for exec_remote; as the
        # default user, user-switching is disabled (auto-detected by the server).
        result = await sandbox.exec([SANDBOX_CLI, "start-server"], user=user)
        if not result.success:
            raise RuntimeError(f"Failed to start sandbox tools server: {result.stderr}")
    except SandboxInjectionError:
        raise
    except Exception as e:
        raise SandboxInjectionError(
            f"Failed to inject sandbox tools into sandbox: {str(e) or type(e).__name__}",
            cause=e,
        ) from e


ROOT_ACCESS_PROBE_TIMEOUT = 60
"""Seconds the root probe may run before the provider times it out.

Applied through the provider's own ``timeout`` (with no retry), so time spent queued
behind other sandbox commands on a busy host does not count against it.
"""

# Prints Uid and CapEff from /proc/self/status, then the setgroups mode. Shell
# builtins only, so it needs nothing from the image beyond /bin/sh. Root is only
# useful if it can switch users: `cap_drop: [ALL]` leaves it without
# CAP_SETGID/CAP_SETUID, and a user namespace may deny setgroups().
_ROOT_PROBE_CMD = (
    'while read k v; do case "$k" in Uid:|CapEff:) echo "$k $v";; esac; done'
    " < /proc/self/status;"
    " if [ -e /proc/self/setgroups ]; then read s < /proc/self/setgroups; else s=allow; fi;"
    ' echo "setgroups: $s"'
)
_SWITCH_USER_CAPS = (1 << 6) | (1 << 7)  # CAP_SETGID | CAP_SETUID
_ROOT_PROBE_FIELDS = {"Uid", "CapEff", "setgroups"}


async def resolve_root_access(sandbox: SandboxEnvironment) -> RootAccess:
    """The sandbox's recorded root-access decision, probing and recording it if absent.

    Sample init calls this for every sandbox after the trusted files and setup and
    before Inspect begins solver/agent execution, so the agent's own commands cannot
    influence the outcome; a sandbox used without sample init is probed on first use
    instead. The decision is never revisited (a probe run after the agent's commands
    could be made to fail by them). An eval's recording proxy shares it with the
    provider object behind it, which ``as_type()`` hands out, in both directions: a
    decision that object already carries is adopted (a provider may return one
    object under several names), and a fresh probe is recorded on both. In an eval
    the probe is one ``SandboxEvent`` in the sample's init span: the durable record
    of which sandbox reached which verdict, for a security-relevant decision.
    """
    if sandbox._root_access is None:
        inner = (
            sandbox._sandbox if isinstance(sandbox, SandboxEnvironmentProxy) else None
        )
        # belt and suspenders in case the provider forgot to call __init__
        recorded: RootAccess | None = getattr(inner, "_root_access", None)
        if recorded is not None:
            sandbox._root_access = recorded
            return recorded
        access = await _probe_root_access(sandbox)
        trace_message(
            logger, TRACE_SANDBOX_TOOLS, f"root access {access.state}: {access.reason}"
        )
        sandbox._root_access = access
        if inner is not None:
            inner._root_access = access
    return sandbox._root_access


async def _probe_root_access(sandbox: SandboxEnvironment) -> RootAccess:
    """Probe ``sandbox`` for usable root. Never raises: every outcome is a result."""
    try:
        probe = await privileged_shell(
            sandbox,
            _ROOT_PROBE_CMD,
            user=_root_probe_user(sandbox),
            timeout=ROOT_ACCESS_PROBE_TIMEOUT,
            timeout_retry=False,
        )
    except (SandboxUnavailableError, TimeoutError) as ex:
        return RootAccess("failed", f"root probe did not complete: {ex}", ex)
    except Exception as ex:
        # Broad catch is deliberate: providers signal "cannot exec as root" with
        # provider-specific exception types, so no narrower type is available.
        return RootAccess(
            "ambiguous", f"root probe raised {type(ex).__name__}: {ex}", ex
        )
    return _root_access_verdict(probe)


def _root_probe_user(sandbox: SandboxEnvironment) -> str | None:
    """``root``, except for the built-in local provider.

    ``LocalSandboxEnvironment`` ignores ``user`` (and warns whenever one is given)
    and runs everything as the current user, so its own identity is the verdict.
    """
    inner = (
        sandbox._sandbox if isinstance(sandbox, SandboxEnvironmentProxy) else sandbox
    )
    return None if isinstance(inner, LocalSandboxEnvironment) else "root"


def _root_access_verdict(probe: ExecResult[str]) -> RootAccess:
    """Read the probe's output; valid Uid, CapEff and setgroups fields are a verdict."""
    fields = _fields(probe.stdout)
    if not fields.keys() >= _ROOT_PROBE_FIELDS:
        return RootAccess(
            "ambiguous",
            f"root probe produced no verdict (exit status {probe.returncode}): "
            f"{probe.stderr or probe.stdout!r}",
        )
    try:
        uid = fields["Uid"].split()[0]
        if uid != "0":
            return RootAccess("unusable", f"commands run as uid {uid}, not as root")
        cap_eff, setgroups = fields["CapEff"].strip(), fields["setgroups"].strip()
        caps = int(cap_eff, 16)
    except (IndexError, ValueError):
        return RootAccess(
            "ambiguous", f"root probe output could not be parsed: {probe.stdout!r}"
        )
    if caps & _SWITCH_USER_CAPS != _SWITCH_USER_CAPS or setgroups != "allow":
        return RootAccess(
            "unusable",
            f"root cannot switch users (CapEff {cap_eff}, setgroups {setgroups})",
        )
    return RootAccess("usable", "commands run as uid 0 and root can switch users")


# Shell builtins only: numeric ids from /proc so uids with no passwd entry work.
_DEFAULT_USER_CMD = (
    'while read k v; do case "$k" in Uid:|Gid:|Groups:) echo "$k $v";; esac; done'
    ' < /proc/self/status; echo "HOME: $HOME"; echo "HOME_SET: ${HOME+1}"'
)


async def _detect_default_user(sandbox: SandboxEnvironment) -> SandboxDefaultUser:
    try:
        result = await privileged_shell(sandbox, _DEFAULT_USER_CMD, user=None)
    except Exception as ex:
        raise SandboxDefaultUserError(
            f"Failed to detect sandbox default user: {ex}"
        ) from ex
    if not result.success:
        raise SandboxDefaultUserError(
            f"Failed to detect sandbox default user: {result.stderr}"
        )
    try:
        return _parse_default_user(result.stdout)
    except (KeyError, IndexError, ValueError) as e:
        raise SandboxDefaultUserError(
            f"Failed to parse sandbox default user from {result.stdout!r}: {e!r}"
        ) from e


def _fields(output: str) -> dict[str, str]:
    """`key: value` lines of a probe, keyed by name.

    The last occurrence wins: a login banner prints before the probe output, so a
    banner line that happens to look like a field cannot shadow the real value.
    """
    lines = output.splitlines()
    return {k: v for k, _, v in (ln.partition(":") for ln in lines) if _}


def _parse_default_user(output: str) -> SandboxDefaultUser:
    fields = _fields(output)
    return SandboxDefaultUser(
        uid=int(fields["Uid"].split()[0]),
        gid=int(fields["Gid"].split()[0]),
        groups=[int(g) for g in fields["Groups"].split()],
        home=fields["HOME"].strip() if fields["HOME_SET"].strip() == "1" else None,
    )


_EXTRACT_TIMEOUT = 600
"""Bounds the archive transfer and extraction (docker `write_file`'s timeout, which
carried the transfer before); a timeout also arms compose's retry of a hung exec."""


async def _extract_tools_tree(
    sandbox: SandboxEnvironment, name: str, gz_bytes: bytes, user: str | None
) -> None:
    """Extract the gzipped onedir tar into SANDBOX_TOOLS_DIR.

    The archive travels to `tar` on stdin, so no copy of it exists at a path another
    principal could write to before the tools user reads it. `write_file` cannot do
    this: it has no `user` parameter, so it stages as the default user, and a
    root-owned 0700 directory is closed to that user. Large binary stdin is part of the
    sandbox contract (`self_check`), though a provider that inlines stdin into a shell
    script may cap it lower; the uncompressed fallback is the largest payload here.
    Extraction runs through the framework-directory helper, so `tar` unpacks into the
    verified directory object (its cwd) rather than into whatever the path names at
    that moment.

    Optimistic path: ship the compressed artifact and extract with `tar xzf`. If the
    container's `tar` lacks gzip support, fall back to injecting an uncompressed tar,
    which only needs plain `tar xf` (the broadest assumption). The uncompressed tar is
    cached in the binaries dir so we decompress at most once per artifact.

    A failing `tar` exits before reading stdin, and providers then raise on the broken
    stdin write instead of returning tar's status, so on failure the wrapper drains
    stdin and fails explicitly.
    """
    result = await exec_in_framework_directory(
        sandbox,
        SANDBOX_TOOLS_DIR,
        ["sh", "-c", "tar xzf - || { cat >/dev/null; exit 1; }"],
        user=user,
        expected_uid=expected_uid_for(user),
        input=gz_bytes,
        timeout=_EXTRACT_TIMEOUT,
    )
    if result.success:
        return

    # Fallback: the container's tar can't gunzip. Inject the uncompressed tar.
    trace_message(
        logger,
        TRACE_SANDBOX_TOOLS,
        f"tar xzf failed ({result.stderr.strip()}); retrying with uncompressed tar",
    )
    result = await exec_in_framework_directory(
        sandbox,
        SANDBOX_TOOLS_DIR,
        ["sh", "-c", "tar xf - || { cat >/dev/null; exit 1; }"],
        user=user,
        expected_uid=expected_uid_for(user),
        input=_uncompressed_tar_bytes(name, gz_bytes),
        timeout=_EXTRACT_TIMEOUT,
    )
    if not result.success:
        raise RuntimeError(f"Failed to extract sandbox tools: {result.stderr}")


def _uncompressed_tar_bytes(name: str, gz_bytes: bytes) -> bytes:
    """Return the uncompressed tar for an artifact, caching it in the binaries dir.

    Used only by the fallback extraction path. Decompresses once and caches the result
    next to the gzipped artifact (as `<name>.tar`) so repeated injections into
    gzip-less sandboxes reuse it rather than re-decompressing each time. The write is
    atomic so concurrent injections can't observe a partial file. Caching is
    best-effort: if the binaries dir isn't writable (e.g. a locked-down install) we
    just return the decompressed bytes rather than failing injection.
    """
    binaries_path = _binaries_dir()
    cache_path = binaries_path / f"{name}.tar"
    if cache_path.exists():
        return cache_path.read_bytes()

    tar_bytes = gzip.decompress(gz_bytes)
    try:
        binaries_path.mkdir(exist_ok=True)
        tmp_path = cache_path.with_suffix(".tar.tmp")
        tmp_path.write_bytes(tar_bytes)
        os.replace(tmp_path, cache_path)
    except OSError as ex:
        trace_message(
            logger, TRACE_SANDBOX_TOOLS, f"could not cache uncompressed tar: {ex}"
        )
    return tar_bytes


@asynccontextmanager
async def _open_executable(executable: str) -> AsyncIterator[BinaryIO]:
    """Open the executable file from the binaries package."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        with resources.path("inspect_ai.binaries", executable) as executable_path:
            with open(executable_path, "rb") as f:
                yield f


def _prompt_user_action(
    message: str, executable_name: str, arch: Architecture, musl: bool
) -> None:
    """Prompt user for confirmation and raise PrerequisiteError if declined.

    Args:
        message: The message to display to the user
        executable_name: Name of the executable for error message
        arch: Architecture for build instructions
        musl: Whether the missing executable is the musl variant (adds --musl)

    Raises:
        PrerequisiteError: If user declines the action
    """
    if sys.stdin.isatty():
        with input_screen():
            response = Prompt.ask(
                message,
                choices=["y", "n"],
                default="y",
                case_sensitive=False,
            )
    else:
        # non-interactive terminal
        response = "n"

    if response != "y":
        build_cmd = (
            "python src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py "
            f"--arch {arch}" + (" --musl" if musl else "")
        )
        raise PrerequisiteError(
            f"Container tools executable {executable_name} is required but not present. "
            f"To build it, run: {build_cmd}"
        )


@asynccontextmanager
async def _open_executable_for_arch(
    arch: Architecture,
    musl: bool,
) -> AsyncIterator[tuple[str, BinaryIO]]:
    install_state = _get_install_state()

    executable_name = _get_executable_name(arch, install_state == "edited", musl)

    trace_message(logger, TRACE_SANDBOX_TOOLS, f"looking for {executable_name}")

    # Only let one task at a time try to resolve the file.
    async with concurrency(executable_name, 1, visible=False):
        # Local Executable Check
        try:
            async with _open_executable(executable_name) as f:
                trace_message(logger, TRACE_SANDBOX_TOOLS, f"found {executable_name}")
                yield executable_name, f
                return
        except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
            if install_state == "pypi":
                if musl:
                    trace_message(
                        logger,
                        TRACE_SANDBOX_TOOLS,
                        f"musl executable {executable_name} not bundled in PyPI package; attempting S3 download",
                    )
                else:
                    msg = f"Tool support executable {executable_name} is missing from the PyPI package installation. This indicates a problem with the package. Please reinstall inspect_ai."
                    # TODO: once we get the github CI/CD actions robust, this should be fatal
                    # raise PrerequisiteError(msg)
                    warn_once(logger, msg)

        # S3 Download Attempt. "pypi" might be wrongly detected, e.g., when UV_NO_INSTALLER_METADATA=1
        if install_state in {"clean", "pypi"}:
            if await _download_from_s3(executable_name):
                async with _open_executable(executable_name) as f:
                    trace_message(
                        logger,
                        TRACE_SANDBOX_TOOLS,
                        f"downloaded {executable_name} from s3",
                    )
                    yield executable_name, f
                    return
            # TODO: One could argue that we should not fall through here. If they
            # haven't made any edits to sandbox_tools, they 100% should be able to
            # download from S3. This scenario is similar to the pypi error just above.

        # Build it locally
        await _build_it(arch, musl, executable_name)

        async with _open_executable(executable_name) as f:
            yield executable_name, f


def _get_sandbox_tools_version() -> str:
    """Get the container tools version from sandbox_tools_version.txt file."""
    # Look in the same directory as this module
    version_file = Path(__file__).parent / "sandbox_tools_version.txt"
    return version_file.read_text().strip()


def _get_executable_name(arch: Architecture, dev: bool, musl: bool) -> str:
    return config_to_filename(
        SandboxToolsBuildConfig(
            arch=arch,
            version=int(_get_sandbox_tools_version()),
            suffix="dev" if dev else None,
            musl=musl,
        )
    )


def _binaries_dir() -> Path:
    return Path(inspect_ai.__file__).parent / "binaries"


async def _download_from_s3(filename: str) -> bool:
    """Download executable from S3, verified against the vendored SHA256SUMS.

    Returns True on a download, False when the object is missing from S3
    (403/404 — not yet published; the caller falls through to the local-build
    tier). A digest mismatch or a missing sums entry must never be conflated
    with "missing" — they are the tampering/corruption signals this
    verification exists to surface. They raise ``PrerequisiteError`` (reaching
    the user wrapped in SandboxInjectionError) with nothing written to the
    binaries directory.
    """
    try:
        # Raises if the sums file is unreadable or has no entry for this name —
        # deliberately before any network I/O.
        expected_sha256 = lookup_digest(filename)
    except RuntimeError as e:
        raise PrerequisiteError(
            f"Cannot verify sandbox tools executable {filename}: {e} If "
            f"reinstalling inspect_ai does not resolve this, report it to the "
            f"inspect_ai maintainers rather than retrying."
        ) from e

    binaries_path = _binaries_dir()
    binaries_path.mkdir(exist_ok=True)
    executable_path = binaries_path / filename
    url = f"{_BUCKET_BASE_URL}/{filename}"

    try:
        await anyio.to_thread.run_sync(
            _download_and_verify_blocking,
            url,
            expected_sha256,
            executable_path,
        )
        return True
    except ValueError as e:
        raise PrerequisiteError(
            f"Digest verification failed for {filename} downloaded from "
            f"S3: {e}. The published artifact does not match the digest "
            f"pinned in this inspect_ai release, which may indicate a "
            f"compromised or corrupted artifact — please report this to "
            f"the inspect_ai maintainers rather than retrying."
        ) from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 404):
            print(f"Executable '{filename}' not found on S3")
            return False
        raise


def _download_and_verify_blocking(url: str, sha256: str, dest: Path) -> None:
    """Download ``url`` to ``dest``, verified against ``sha256`` (blocking).

    ``download()`` streams to a *fixed* sibling tempfile, so two processes
    fetching the same ``dest`` (e.g. parallel evals on a fresh install racing
    for the musl artifact — the in-process ``concurrency()`` guard doesn't
    cover that) could interleave writes and rename unverified bytes into
    place. Mirror ``_restic/resolver.py``: give ``download()`` a unique
    mkstemp destination and do our own final ``os.replace``.

    Raises ``ValueError`` on digest mismatch and ``httpx.HTTPStatusError`` on
    non-retryable HTTP errors (both from ``download()``).
    """
    fd, tmp_path = tempfile.mkstemp(prefix=f"{dest.name}.", dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        download(url, sha256, tmp, timeout=60)
        tmp.chmod(0o755)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


async def _build_it(arch: Architecture, musl: bool, dev_executable_name: str) -> None:
    _prompt_user_action(
        f"Executable '{dev_executable_name}' not found. Build locally? (requires Docker)",
        dev_executable_name,
        arch,
        musl,
    )

    # Find the build script
    build_script_path = Path(__file__).parent / "build_within_container.py"

    if not build_script_path.exists():
        raise FileNotFoundError(f"Build script not found at {build_script_path}")

    print(f"Building missing executable {dev_executable_name}...")

    # Run the build script
    subprocess.run(
        [sys.executable, str(build_script_path), "--arch", arch]
        + (["--musl"] if musl else []),
        capture_output=True,
        text=True,
        check=True,
    )

    print(f"Successfully built {dev_executable_name}")


_INSTALL_STATE_OVERRIDE_ENV = "INSPECT_SANDBOX_TOOLS_INSTALL_STATE"


def _install_state_override() -> InstallState | None:
    """Read the CI escape-hatch env var; None if unset.

    Release-gate jobs force "clean" so the non-dev binary name is resolved
    even when version.txt has diverged from main on a release PR. See #3704.
    """
    match os.environ.get(_INSTALL_STATE_OVERRIDE_ENV):
        case None:
            return None
        case "pypi" | "clean" | "edited" as s:
            return s
        case other:
            raise ValueError(
                f"{_INSTALL_STATE_OVERRIDE_ENV}={other!r} invalid; "
                f"must be one of {get_args(InstallState)}"
            )


def _get_install_state() -> InstallState:
    """Detect the state of the inspect-ai installation."""
    if (override := _install_state_override()) is not None:
        return override

    if (direct_url := get_package_direct_url("inspect-ai")) is None:
        return "pypi"

    if (
        editable_url := (
            direct_url.url
            if direct_url.dir_info and direct_url.dir_info.editable
            else None
        )
    ) is None:
        return "clean"

    return _check_main_divergence(editable_url)


def _check_main_divergence(url: str) -> Literal["clean", "edited"]:
    """Check if there are changes to sandbox tools files relative to main.

    Only changes that ship in the built binary count: docs (`*.md`,
    `design/`) and `tests/` under the injectable tree are excluded, mirroring
    the CI `injectable_src` paths-filter (`.github/workflows/build.yml`,
    `detect-slow` job) — keep the two in sync. CI skips the `-dev` build for
    such changes, so classifying them "edited" would resolve a `-dev` binary
    that never gets built (and prompt local developers to build one for a
    doc-only edit).

    Returns:
        Literal["clean", "edited"]: The state of changes to sandbox tools files.
            - "clean": No changes to sandbox tools files relative to main branch,
              or git is not available/functioning
            - "edited": Changes detected to tool support files - either
              uncommitted changes (staged/unstaged) or committed changes relative
              to main branch
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme != "file":
        return "clean"

    git_root = Path(unquote(parsed_url.path))

    trace_message(
        logger, TRACE_SANDBOX_TOOLS, f"_check_for_changes: checking {git_root=}"
    )

    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
            cwd=git_root,
        )
        if result.returncode != 0:
            trace_message(
                logger,
                TRACE_SANDBOX_TOOLS,
                f"_check_for_changes: git rev-parse failed {result}",
            )
            # Not a git repo, assume clean (not sure this is even possible)
            return "clean"

        # Check for staged or unstaged changes to relevant paths. Each entry
        # is a pathspec list: the injectable tree carries excludes matching
        # the CI injectable_src filter (see docstring).
        pathspecs_to_check = [
            ["src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt"],
            [
                "src/inspect_sandbox_tools",
                ":(exclude)src/inspect_sandbox_tools/tests",
                ":(exclude)src/inspect_sandbox_tools/design",
                ":(exclude,glob)src/inspect_sandbox_tools/**/*.md",
            ],
        ]

        for pathspecs in pathspecs_to_check:
            # Check for uncommitted changes (staged + unstaged)
            result = subprocess.run(
                ["git", "status", "--porcelain", "--", *pathspecs],
                capture_output=True,
                text=True,
                check=False,
                cwd=git_root,
            )
            if result.returncode == 0 and result.stdout.strip():
                trace_message(
                    logger,
                    TRACE_SANDBOX_TOOLS,
                    f"_check_for_changes: uncommitted changes (staged + unstaged) detected for {pathspecs[0]}",
                )
                return "edited"

        main_ref = _resolve_main_ref(git_root)
        if main_ref is None:
            trace_message(
                logger,
                TRACE_SANDBOX_TOOLS,
                "_check_for_changes: no main branch ref resolved",
            )
            return "clean"

        for pathspecs in pathspecs_to_check:
            # Check for committed changes relative to the freshest main ref
            # available in common checkouts.
            result = subprocess.run(
                ["git", "diff", main_ref, "--quiet", "--", *pathspecs],
                capture_output=True,
                text=True,
                check=False,
                cwd=git_root,
            )
            if result.returncode == 1:
                trace_message(
                    logger,
                    TRACE_SANDBOX_TOOLS,
                    f"_check_for_changes: diff's from {main_ref} detected for {pathspecs[0]}",
                )
                return "edited"
            elif result.returncode != 0:
                trace_message(
                    logger,
                    TRACE_SANDBOX_TOOLS,
                    f"_check_for_changes: git diff failed for {pathspecs[0]}: {result}",
                )
                return "clean"

        trace_message(
            logger, TRACE_SANDBOX_TOOLS, "_check_for_changes: do changes detected"
        )
        return "clean"

    except (subprocess.SubprocessError, FileNotFoundError) as ex:
        # If git commands fail, assume clean
        trace_message(
            logger, TRACE_SANDBOX_TOOLS, f"_check_for_changes: caught exception {ex}"
        )
        return "clean"


def _resolve_main_ref(git_root: Path) -> str | None:
    for ref in ("origin/main", "main"):
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            capture_output=True,
            text=True,
            check=False,
            cwd=git_root,
        )
        if result.returncode == 0:
            return ref
    return None
