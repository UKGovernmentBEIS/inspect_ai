import gzip
import os
import subprocess
import sys
import warnings
from contextlib import asynccontextmanager
from importlib import resources
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Literal, get_args
from urllib.parse import unquote, urlparse

import httpx
from rich.prompt import Prompt

import inspect_ai
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai._util.package import get_package_direct_url
from inspect_ai._util.trace import trace_message
from inspect_ai.util import input_screen
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._sandbox._cli import SANDBOX_CLI, SANDBOX_TOOLS_DIR
from inspect_ai.util._sandbox.context import (
    SandboxInjectable,
    sandbox_file_detector,
    sandbox_with_injection,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.recon import Architecture, detect_sandbox_os

from ._build_config import (
    SandboxToolsBuildConfig,
    config_to_filename,
)

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
            sandbox_file_detector(SANDBOX_CLI),
            _inject_container_tools_code,
        ),
        name=sandbox_name,
        target=sandbox,
    )


async def _inject_container_tools_code(sandbox: SandboxEnvironment) -> None:
    try:
        info = await detect_sandbox_os(sandbox)
        musl = info.get("libc") == "musl"

        async with _open_executable_for_arch(info["architecture"], musl) as (name, f):
            gz_bytes = f.read()  # gzipped tar of the PyInstaller --onedir tree

        # Create the install dir as root if possible so the tree is root-owned and
        # can be hidden from the agent; fall back to the default user for rootless
        # sandboxes (where user-switching will be disabled, auto-detected by the
        # server).
        if (
            await sandbox.exec(["mkdir", "-p", SANDBOX_TOOLS_DIR], user="root")
        ).success:
            sandbox._tools_user = "root"
        else:
            result = await sandbox.exec(["mkdir", "-p", SANDBOX_TOOLS_DIR])
            if not result.success:
                raise RuntimeError(
                    f"Failed to create sandbox tools dir: {result.stderr}"
                )

        await _extract_tools_tree(sandbox, name, gz_bytes, sandbox._tools_user)

        # When running as root, restrict the tree so the agent can neither read nor
        # execute the tools. The default user (the one that runs `exec`) is root, so
        # this does not impede tool calls.
        if sandbox._tools_user == "root":
            result = await sandbox.exec(
                ["chmod", "700", SANDBOX_TOOLS_DIR], user="root"
            )
            if not result.success:
                raise RuntimeError(
                    f"Failed to chmod sandbox tools dir: {result.stderr}"
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


async def _extract_tools_tree(
    sandbox: SandboxEnvironment, name: str, gz_bytes: bytes, user: str | None
) -> None:
    """Extract the gzipped onedir tar into SANDBOX_TOOLS_DIR.

    The artifact is staged to a temp file via write_file (which base64-encodes binary
    content reliably; raw binary stdin through exec is not safe) and then extracted.

    Optimistic path: ship the compressed artifact and extract with `tar xzf`. If the
    container's `tar` lacks gzip support, fall back to injecting an uncompressed tar,
    which only needs plain `tar xf` (the broadest assumption). The uncompressed tar is
    cached in the binaries dir so we decompress at most once per artifact.
    """
    gz_tmp = f"{SANDBOX_TOOLS_DIR}.pkg.tgz"
    await sandbox.write_file(gz_tmp, gz_bytes)
    result = await sandbox.exec(
        ["tar", "xzf", gz_tmp, "-C", SANDBOX_TOOLS_DIR], user=user
    )
    await sandbox.exec(["rm", "-f", gz_tmp], user=user)
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
    result = await sandbox.exec(
        ["tar", "xf", tar_tmp, "-C", SANDBOX_TOOLS_DIR], user=user
    )
    await sandbox.exec(["rm", "-f", tar_tmp], user=user)
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
    binaries_path = Path(inspect_ai.__file__).parent / "binaries"
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


async def _download_from_s3(filename: str) -> bool:
    """Download executable from S3. Returns True if successful, False otherwise.

    Handles expected failures (404 - not yet promoted) silently.
    Logs unexpected failures but doesn't raise exceptions.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Download the executable
            response = await client.get(f"{_BUCKET_BASE_URL}/{filename}")
            response.raise_for_status()

            # Save to binaries directory
            binaries_path = Path(inspect_ai.__file__).parent / "binaries"
            binaries_path.mkdir(exist_ok=True)

            # Save with versioned name to match what we're looking for
            executable_path = binaries_path / filename
            executable_path.write_bytes(response.content)
            executable_path.chmod(0o755)

            return True

    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 404):
            print(f"Executable '{filename}' not found on S3")
            return False
        raise


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

        # Check for staged or unstaged changes to relevant paths
        paths_to_check = [
            "src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt",
            "src/inspect_sandbox_tools",
        ]

        for path in paths_to_check:
            # Check for uncommitted changes (staged + unstaged)
            result = subprocess.run(
                ["git", "status", "--porcelain", path],
                capture_output=True,
                text=True,
                check=False,
                cwd=git_root,
            )
            if result.returncode == 0 and result.stdout.strip():
                trace_message(
                    logger,
                    TRACE_SANDBOX_TOOLS,
                    f"_check_for_changes: uncommitted changes (staged + unstaged) detected for {path}",
                )
                return "edited"

            # Check for committed changes relative to main
            result = subprocess.run(
                ["git", "diff", "main", "--quiet", path],
                capture_output=True,
                text=True,
                check=False,
                cwd=git_root,
            )
            if result.returncode != 0:
                trace_message(
                    logger,
                    TRACE_SANDBOX_TOOLS,
                    f"_check_for_changes: diff's from main detected for {path}",
                )
                return "edited"

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
