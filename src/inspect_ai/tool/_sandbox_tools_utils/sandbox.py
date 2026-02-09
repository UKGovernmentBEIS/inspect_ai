import subprocess
import sys
import warnings
from contextlib import asynccontextmanager
from importlib import resources
from logging import getLogger
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Literal
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
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
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
    *, sandbox_name: str | None = None
) -> SandboxEnvironment:
    """Create a sandbox environment with sandbox tools injection.

    Args:
        sandbox_name: Optional name for the sandbox environment.

    Returns:
        A sandbox environment with container tools injected.
    """
    return await sandbox_with_injection(
        SandboxInjectable(
            sandbox_file_detector(SANDBOX_CLI),
            _inject_container_tools_code,
        ),
        name=sandbox_name,
    )


async def _inject_container_tools_code(sandbox: SandboxEnvironment) -> None:
    try:
        info = await detect_sandbox_os(sandbox)

        async with _open_executable_for_arch(info["architecture"]) as (_, f):
            # TODO: The first tuple member, filename, isn't currently used, but it will be
            await sandbox.write_file(SANDBOX_CLI, f.read())
            # .write_file used `tee` which dropped execute permissions
            result = await sandbox.exec(["chmod", "+x", SANDBOX_CLI], user="root")
            if not result.success:
                raise RuntimeError(
                    f"Failed to chmod sandbox tools binary: {result.stderr}"
                )
    except Exception as e:
        raise SandboxInjectionError(
            f"Failed to inject sandbox tools into sandbox: {e}", cause=e
        ) from e


@asynccontextmanager
async def _open_executable(executable: str) -> AsyncIterator[BinaryIO]:
    """Open the executable file from the binaries package."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        with resources.path("inspect_ai.binaries", executable) as executable_path:
            with open(executable_path, "rb") as f:
                yield f


def _prompt_user_action(message: str, executable_name: str, arch: Architecture) -> None:
    """Prompt user for confirmation and raise PrerequisiteError if declined.

    Args:
        message: The message to display to the user
        executable_name: Name of the executable for error message
        arch: Architecture for build instructions

    Raises:
        PrerequisiteError: If user declines the action
    """
    with input_screen():
        response = Prompt.ask(
            message,
            choices=["y", "n"],
            default="y",
            case_sensitive=False,
        )
        if response != "y":
            raise PrerequisiteError(
                f"Container tools executable {executable_name} is required but not present. "
                f"To build it, run: python src/inspect_ai/tool/sandbox_tools/build_within_container.py --arch {arch}"
            )


@asynccontextmanager
async def _open_executable_for_arch(
    arch: Architecture,
) -> AsyncIterator[tuple[str, BinaryIO]]:
    install_state = _get_install_state()

    executable_name = _get_executable_name(arch, install_state == "edited")

    trace_message(logger, TRACE_SANDBOX_TOOLS, f"looking for {executable_name}")

    # Only let one task at a time try to resolve the file.
    async with concurrency(executable_name, 1, visible=False):
        # Local Executable Check
        try:
            async with _open_executable(executable_name) as f:
                trace_message(logger, TRACE_SANDBOX_TOOLS, f"found {executable_name}")
                yield executable_name, f
                return
        except (FileNotFoundError, ModuleNotFoundError):
            if install_state == "pypi":
                msg = f"Tool support executable {executable_name} is missing from the PyPI package installation. This indicates a problem with the package. Please reinstall inspect_ai."
                # TODO: once we get the github CI/CD actions robust, this should be fatal
                # raise PrerequisiteError(msg)
                warn_once(logger, msg)

        # S3 Download Attempt
        if install_state == "clean":
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
        await _build_it(arch, executable_name)

        async with _open_executable(executable_name) as f:
            yield executable_name, f


def _get_sandbox_tools_version() -> str:
    """Get the container tools version from sandbox_tools_version.txt file."""
    # Look in the same directory as this module
    version_file = Path(__file__).parent / "sandbox_tools_version.txt"
    return version_file.read_text().strip()


def _get_executable_name(arch: Architecture, dev: bool) -> str:
    return config_to_filename(
        SandboxToolsBuildConfig(
            arch=arch,
            version=int(_get_sandbox_tools_version()),
            suffix="dev" if dev else None,
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


async def _build_it(arch: Architecture, dev_executable_name: str) -> None:
    _prompt_user_action(
        f"Executable '{dev_executable_name}' not found. Build locally? (requires Docker)",
        dev_executable_name,
        arch,
    )

    # Find the build script
    build_script_path = Path(__file__).parent / "build_within_container.py"

    if not build_script_path.exists():
        raise FileNotFoundError(f"Build script not found at {build_script_path}")

    print(f"Building missing executable {dev_executable_name}...")

    # Run the build script
    subprocess.run(
        [sys.executable, str(build_script_path), "--arch", arch],
        capture_output=True,
        text=True,
        check=True,
    )

    print(f"Successfully built {dev_executable_name}")


def _get_install_state() -> InstallState:
    """Detect the state of the inspect-ai installation."""
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
