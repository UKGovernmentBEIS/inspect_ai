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
    FrameworkDirectoryUnavailableError,
    FrameworkDirectoryUserError,
    ensure_framework_directory,
    exec_in_framework_directory,
    verify_framework_directory,
)
from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_with_injection,
)
from inspect_ai.util._sandbox.environment import (
    SandboxDefaultUser,
    SandboxEnvironment,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._sandbox.recon import Architecture, detect_sandbox_os

from ._build_config import (
    SandboxToolsBuildConfig,
    config_to_filename,
)
from ._digests import lookup_digest

_BUCKET_BASE_URL = "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com"

logger = getLogger(__name__)


TRACE_SANDBOX_TOOLS = "Sandbox Tools"


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

    The tools user is known once an injection has run on this sandbox object (root
    when the sandbox can exec as root, otherwise the default user). Before that (a
    fresh object attached to a sandbox that may already hold an installation) the
    check runs as root first, because a root-owned 0700 tree cannot even be entered
    by the default user; a trustworthy root installation found that way is adopted
    by recording root as the tools user. Only when the sandbox cannot exec as root
    at all (it refuses the user, or silently runs the command as someone else) is the
    default user's view consulted. A trustworthy installation found there is used for
    this call, but the default user is recorded as the tools user only when the root
    failure was definitive: the helper's uid-mismatch verdict, which says the provider
    ran the command as someone else and will keep doing so. A provider exception or a
    failing exit status may be transient on a root-capable sandbox, and pinning on it
    would let a tree the agent planted under its own uid be adopted for the rest of
    the sample; instead the next call probes root again, root sees the planted tree as
    a violation, and injection fails loud. The cost falls only on providers that
    refuse root by exception: one failing root exec per tool call until injection
    runs on this object and records the tools user itself. When the default user's
    view finds an existing installation, injection never runs on this object, so
    the extra exec repeats for the object's lifetime.

    The probe records no transcript events: it repeats on every tool call and its
    argv carries the whole verification script, so logging it would add kilobytes
    of identical shell to the transcript per call (the injection itself, which runs
    once per sandbox, is still recorded).
    """
    try:
        with _without_sandbox_events(sandbox):
            return await _detect_sandbox_tools(sandbox)
    except Exception as ex:
        # Broad catch is deliberate: detectors run against every candidate sandbox
        # and providers raise provider-specific types for an unusable one. Treat it
        # as "not installed"; injection then surfaces any real failure.
        trace_message(logger, TRACE_SANDBOX_TOOLS, f"tools detection failed: {ex}")
        return False


async def _detect_sandbox_tools(sandbox: SandboxEnvironment) -> bool:
    if sandbox._tools_user_resolved or sandbox._tools_user is not None:
        return await _tools_installed_as(sandbox, sandbox._tools_user)

    try:
        installed = await _tools_installed_as(sandbox, "root")
    except FrameworkDirectoryUnavailableError:
        raise
    except Exception as ex:
        # Broad catch is deliberate: providers signal "cannot exec as root" by
        # raising provider-specific exception types or by a failing exit status
        # (which the helper reports as a RuntimeError when its check never ran).
        # Only the uid-mismatch verdict is a definitive "this sandbox has no root";
        # anything else may be transient, so it must not pin the tools user (see
        # the docstring above).
        trace_message(
            logger,
            TRACE_SANDBOX_TOOLS,
            f"root tools detection failed; checking as default user: {ex}",
        )
        installed = await _tools_installed_as(sandbox, None)
        if installed and isinstance(ex, FrameworkDirectoryUserError):
            await _set_tools_user(sandbox, None)
        return installed
    if installed:
        await _set_tools_user(sandbox, "root")
    return installed


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


async def _set_tools_user(sandbox: SandboxEnvironment, user: str | None) -> None:
    """Record which user the sandbox tools run as (``None`` = default user).

    With a root tools user, also capture the default exec identity so tool calls
    without an explicit user can run as it (see ``_detect_default_user``).
    """
    default_user = await _detect_default_user(sandbox) if user == "root" else None
    sandbox._tools_user = user
    sandbox._tools_user_resolved = True
    sandbox._tools_default_user = default_user


def _expected_uid(user: str | None) -> int | None:
    """The uid the helper must actually run as for ``user``.

    Only root has a uid known to the host. Pinning it makes a provider that ignores
    or downgrades ``user`` (``LocalSandboxEnvironment`` does) fail the root probe
    instead of passing off the default user's directory as root's.
    """
    return 0 if user == "root" else None


async def _tools_installed_as(sandbox: SandboxEnvironment, user: str | None) -> bool:
    """Check for a trustworthy installation from ``user``'s point of view.

    Returns False when the tools directory is missing, violates the contract, or
    does not hold a regular-file launcher (injection then creates it, fails loudly,
    or re-extracts). Raises when the check did not run (the provider cannot exec
    as ``user``) or could not be performed.
    """
    try:
        result = await exec_in_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            ["stat", "-c", "%f", SANDBOX_TOOLS_BASE_NAME],
            user=user,
            expected_uid=_expected_uid(user),
        )
    except FrameworkDirectoryNotFoundError:
        return False
    except FrameworkDirectoryError as ex:
        trace_message(logger, TRACE_SANDBOX_TOOLS, f"tools dir not reusable: {ex}")
        return False
    return result.success and _is_regular_file_mode(result.stdout)


def _is_regular_file_mode(stat_output: str) -> bool:
    """Whether ``stat -c %f`` output (raw st_mode in hex) denotes a regular file.

    The raw mode is used instead of ``%F`` because GNU ``stat`` localizes the
    latter's type names, so a container with a non-C locale would never match
    "regular file". ``stat`` does not follow symlinks, so a symlink at the launcher
    path reports its own type and is rejected.
    """
    try:
        mode = int(stat_output.strip(), 16)
    except ValueError:
        return False
    return stat.S_ISREG(mode)


async def _inject_container_tools_code(sandbox: SandboxEnvironment) -> None:
    try:
        info = await detect_sandbox_os(sandbox)
        musl = info.get("libc") == "musl"

        async with _open_executable_for_arch(info["architecture"], musl) as (name, f):
            gz_bytes = f.read()  # gzipped tar of the PyInstaller --onedir tree

        # Prepare the install dir as root if possible; fall back to the default user
        # for rootless sandboxes (where user-switching will be disabled,
        # auto-detected by the server). Either way the directory is verified to be a
        # real directory owned by that user with mode 0700 before anything is
        # extracted into it. A root-owned 0700 tree prevents access by other,
        # non-root users, but not by a process running in the sandbox as root. In a
        # rootless sandbox the agent shares the tools user's uid, so a directory that
        # uid owns is tightened to 0700 rather than refused: older releases left
        # rootless installs at 0755 (on the host, for the `local` sandbox).
        if await _create_tools_dir_as_root(sandbox):
            await _set_tools_user(sandbox, "root")
        else:
            await ensure_framework_directory(
                sandbox, SANDBOX_TOOLS_DIR, user=None, repair_mode=True
            )
            await _set_tools_user(sandbox, None)

        await _extract_tools_tree(sandbox, name, gz_bytes, sandbox._tools_user)

        # Re-verify immediately before the launcher runs with the tools user's
        # authority. Extraction targets the verified directory object, so this
        # only fails if the entry at the path was swapped or removed in between.
        await verify_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            user=sandbox._tools_user,
            expected_uid=_expected_uid(sandbox._tools_user),
        )

        # Start the server as root so it can setuid to any user for exec_remote.
        # If root isn't available, fall back to the sandbox's default user —
        # user-switching will be disabled (auto-detected by the server).
        result = await sandbox.exec(
            [SANDBOX_CLI, "start-server"], user=sandbox._tools_user
        )
        if not result.success:
            raise RuntimeError(f"Failed to start sandbox tools server: {result.stderr}")
    except Exception as e:
        raise SandboxInjectionError(
            f"Failed to inject sandbox tools into sandbox: {e}", cause=e
        ) from e


# Root is only useful if it can switch users; e.g. `cap_drop: [ALL]` leaves root
# without CAP_SETGID/CAP_SETUID, and a user namespace may deny setgroups(), so the
# tools must run as the default user instead. Prints CapEff then the setgroups mode.
_ROOT_PROBE_CMD = (
    'while read k v; do case "$k" in Uid:|CapEff:) echo "$k $v";; esac; done'
    " < /proc/self/status;"
    " if [ -e /proc/self/setgroups ]; then read s < /proc/self/setgroups; else s=allow; fi;"
    ' echo "setgroups: $s"'
)
_SWITCH_USER_CAPS = (1 << 6) | (1 << 7)  # CAP_SETGID | CAP_SETUID


async def _create_tools_dir_as_root(sandbox: SandboxEnvironment) -> bool:
    """Prepare the tools dir as root; False if the sandbox cannot exec as root.

    "Cannot exec as root" includes a provider that accepts ``user="root"`` but runs
    the command as someone else (``LocalSandboxEnvironment`` ignores ``user``): the
    helper is told to expect uid 0 and reports the mismatch before creating
    anything, so the rootless path is taken and the tools user is recorded
    truthfully.

    A contract violation reported by the helper (the entry exists but is a symlink,
    is owned by another uid, has the wrong mode, ...) is re-raised rather than
    treated as "no root": falling back to the default user there would let whoever
    planted the entry decide which user the tools run as.
    """
    try:
        probe = await sandbox.exec(["/bin/sh", "-c", _ROOT_PROBE_CMD], user="root")
        fields = _fields(probe.stdout)
        if not probe.success or fields.keys() < {"Uid", "CapEff", "setgroups"}:
            raise RuntimeError(f"root probe failed: {probe.stderr or probe.stdout!r}")
        if fields["Uid"].split()[0] != "0":
            trace_message(
                logger,
                TRACE_SANDBOX_TOOLS,
                "sandbox does not run commands as root; using default user",
            )
            return False
        cap_eff, setgroups = fields["CapEff"].strip(), fields["setgroups"].strip()
        if (
            int(cap_eff, 16) & _SWITCH_USER_CAPS != _SWITCH_USER_CAPS
            or setgroups != "allow"
        ):
            trace_message(
                logger,
                TRACE_SANDBOX_TOOLS,
                f"root cannot switch users (CapEff {cap_eff}, setgroups {setgroups}); "
                "falling back to default user",
            )
            return False
        await ensure_framework_directory(
            sandbox, SANDBOX_TOOLS_DIR, user="root", expected_uid=0
        )
        return True
    except (FrameworkDirectoryError, FrameworkDirectoryUnavailableError):
        raise
    except FrameworkDirectoryUserError as ex:
        trace_message(
            logger,
            TRACE_SANDBOX_TOOLS,
            f"sandbox does not run commands as root; using default user: {ex}",
        )
        return False
    except Exception as ex:
        # Broad catch is deliberate: providers signal "cannot exec as root" by
        # raising provider-specific exception types (or a failing exit status), so
        # no narrower type is available. Trade-off: any other probe failure selects
        # the rootless install.
        trace_message(
            logger,
            TRACE_SANDBOX_TOOLS,
            f"root sandbox tools dir probe failed; falling back to default user: {ex}",
        )
        return False


# Shell builtins only: numeric ids from /proc so uids with no passwd entry work.
_DEFAULT_USER_CMD = (
    'while read k v; do case "$k" in Uid:|Gid:|Groups:) echo "$k $v";; esac; done'
    ' < /proc/self/status; echo "HOME: $HOME"; echo "HOME_SET: ${HOME+1}"'
)


async def _detect_default_user(sandbox: SandboxEnvironment) -> SandboxDefaultUser:
    result = await sandbox.exec(["/bin/sh", "-c", _DEFAULT_USER_CMD])
    if not result.success:
        raise RuntimeError(f"Failed to detect sandbox default user: {result.stderr}")
    try:
        return _parse_default_user(result.stdout)
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(
            f"Failed to parse sandbox default user from {result.stdout!r}: {e!r}"
        ) from e


def _fields(output: str) -> dict[str, str]:
    """`key: value` lines of a probe, keyed by name; the first occurrence wins."""
    lines = reversed(output.splitlines())
    return {k: v for k, _, v in (ln.partition(":") for ln in lines) if _}


def _parse_default_user(output: str) -> SandboxDefaultUser:
    fields = _fields(output)
    return SandboxDefaultUser(
        uid=int(fields["Uid"].split()[0]),
        gid=int(fields["Gid"].split()[0]),
        groups=[int(g) for g in fields["Groups"].split()],
        home=fields["HOME"].strip() if fields["HOME_SET"].strip() == "1" else None,
    )


async def _extract_tools_tree(
    sandbox: SandboxEnvironment, name: str, gz_bytes: bytes, user: str | None
) -> None:
    """Extract the gzipped onedir tar into SANDBOX_TOOLS_DIR.

    The artifact is staged to a temp file via write_file (which base64-encodes binary
    content reliably; raw binary stdin through exec is not safe) and then extracted.
    Extraction runs through the framework-directory helper, so `tar` unpacks into the
    verified directory object (its cwd) rather than into whatever the path names at
    that moment.

    Optimistic path: ship the compressed artifact and extract with `tar xzf`. If the
    container's `tar` lacks gzip support, fall back to injecting an uncompressed tar,
    which only needs plain `tar xf` (the broadest assumption). The uncompressed tar is
    cached in the binaries dir so we decompress at most once per artifact.
    """
    gz_tmp = f"{SANDBOX_TOOLS_DIR}.pkg.tgz"
    await sandbox.write_file(gz_tmp, gz_bytes)
    try:
        result = await exec_in_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            ["tar", "xzf", gz_tmp],
            user=user,
            expected_uid=_expected_uid(user),
        )
    finally:
        await _remove_staged_archive(sandbox, gz_tmp, user)
    if result.success:
        return

    # Fallback: the container's tar can't gunzip. Inject the uncompressed tar.
    trace_message(
        logger,
        TRACE_SANDBOX_TOOLS,
        f"tar xzf failed ({result.stderr.strip()}); retrying with uncompressed tar",
    )
    tar_tmp = f"{SANDBOX_TOOLS_DIR}.pkg.tar"
    await sandbox.write_file(tar_tmp, _uncompressed_tar_bytes(name, gz_bytes))
    try:
        result = await exec_in_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            ["tar", "xf", tar_tmp],
            user=user,
            expected_uid=_expected_uid(user),
        )
    finally:
        await _remove_staged_archive(sandbox, tar_tmp, user)
    if not result.success:
        raise RuntimeError(f"Failed to extract sandbox tools: {result.stderr}")


async def _remove_staged_archive(
    sandbox: SandboxEnvironment, path: str, user: str | None
) -> None:
    """Best-effort removal of a staged archive, as the extraction user.

    Runs through the framework-directory helper rather than as a bare-name ``rm``
    so the command resolves through the helper's pinned ``PATH``, not the image's
    (this runs as root in a root-capable sandbox, and in a ``finally``, so it would
    otherwise run even right after verification refused a planted entry). A helper
    verdict here means the tools directory is gone or untrusted; the archive is then
    left behind rather than masking the exception that is already propagating.
    """
    try:
        result = await exec_in_framework_directory(
            sandbox,
            SANDBOX_TOOLS_DIR,
            ["rm", "-f", path],
            user=user,
            expected_uid=_expected_uid(user),
        )
    except RuntimeError as ex:
        # Covers every helper verdict (all subclass RuntimeError) as well as the
        # helper's own "check never ran" failure; anything else propagates.
        trace_message(
            logger, TRACE_SANDBOX_TOOLS, f"staged archive {path} not removed: {ex}"
        )
        return
    if not result.success:
        trace_message(
            logger,
            TRACE_SANDBOX_TOOLS,
            f"staged archive {path} not removed: {result.stderr.strip()}",
        )


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


# Soft launch of digest verification: failures warn by default and are fatal
# only when this env var is set (any value other than "", "0", "false"). A
# follow-on release makes them fatal unconditionally and removes the var.
STRICT_DIGESTS_VAR = "INSPECT_SANDBOX_TOOLS_STRICT_DIGESTS"


def _strict_digests() -> bool:
    return os.environ.get(STRICT_DIGESTS_VAR, "").lower() not in ("", "0", "false")


async def _download_from_s3(filename: str) -> bool:
    """Download executable from S3, verified against the vendored SHA256SUMS.

    Returns True on a download, False when the object is missing from S3
    (403/404 — not yet published; the caller falls through to the local-build
    tier). A digest mismatch or a missing sums entry must never be conflated
    with "missing" — they are the tampering/corruption signals this
    verification exists to surface. With ``STRICT_DIGESTS_VAR`` set they raise
    (reaching the user wrapped in SandboxInjectionError); by default they log
    a warning and the unverified bytes are used anyway.
    """
    expected_sha256: str | None
    try:
        # Raises if the sums file is unreadable or has no entry for this name —
        # deliberately before any network I/O.
        expected_sha256 = lookup_digest(filename)
    except RuntimeError as e:
        if _strict_digests():
            raise
        warn_once(
            logger,
            f"Sandbox tools digest lookup failed ({e}); downloading without "
            f"verification. This will become a fatal error in a future "
            f"release; set {STRICT_DIGESTS_VAR}=1 to make it fatal now.",
        )
        expected_sha256 = None

    binaries_path = _binaries_dir()
    binaries_path.mkdir(exist_ok=True)
    executable_path = binaries_path / filename
    url = f"{_BUCKET_BASE_URL}/{filename}"

    try:
        if expected_sha256 is not None:
            try:
                await anyio.to_thread.run_sync(
                    _download_and_verify_blocking,
                    url,
                    expected_sha256,
                    executable_path,
                )
                return True
            except ValueError as e:
                message = (
                    f"Digest verification failed for {filename} downloaded from "
                    f"S3: {e}. The published artifact does not match the digest "
                    f"pinned in this inspect_ai release, which may indicate a "
                    f"compromised or corrupted artifact — please report this to "
                    f"the inspect_ai maintainers rather than retrying."
                )
                if _strict_digests():
                    raise PrerequisiteError(message) from e
                warn_once(
                    logger,
                    f"{message} Proceeding with the unverified artifact. This "
                    f"will become a fatal error in a future release; set "
                    f"{STRICT_DIGESTS_VAR}=1 to make it fatal now.",
                )
        # Unverified download — no pinned digest, or verification failed and
        # strict mode is off (download() discarded the mismatching bytes, so
        # fetch again without verification).
        await anyio.to_thread.run_sync(
            _download_unverified_blocking, url, executable_path
        )
        return True
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


def _download_unverified_blocking(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` with no digest check (blocking).

    Soft-launch fallback only (see ``_download_from_s3``). Same unique-tempfile
    + ``os.replace`` discipline as ``_download_and_verify_blocking``.

    Raises ``httpx.HTTPStatusError`` on HTTP errors (no transient retries).
    """
    fd, tmp_path = tempfile.mkstemp(prefix=f"{dest.name}.", dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
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
