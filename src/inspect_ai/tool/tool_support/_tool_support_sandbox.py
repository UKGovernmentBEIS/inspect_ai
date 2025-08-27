import subprocess
import sys
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Literal

import httpx
from rich.prompt import Prompt

import inspect_ai
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import input_screen
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._sandbox._recon import Architecture, detect_sandbox_os
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ._tool_support_build_config import (
    BuildConfig,
    config_to_filename,
)

BUCKET_BASE_URL = "https://inspect-tool-support.s3.us-east-2.amazonaws.com"


InstallState = Literal["pypi", "main", "edited"]
"""Represents the state of the inspect-ai installation.

pypi: PyPI installation
main: Non-PyPI install with no changes relative to main
edited: Non-PyPI install with changes to tool support or version
"""


# TODO: Currently, this logic relies on a specific file existing at a specific path
# this may need to be enhanced to use a dynamic predicate instead. otherwise, how
# would we work on os's with a different directory structure?
SANDBOX_CLI = "/opt/inspect-tool-support"


async def inject_tool_support_code(
    sandbox: SandboxEnvironment, with_browser: bool = False
) -> None:
    info = await detect_sandbox_os(sandbox)
    print(f"attempting to inject_tool_support_code for {info}")

    async with _open_executable_for_arch(
        info["architecture"], with_browser=with_browser
    ) as (_, f):
        # TODO: The first tuple member, filename, isn't currently used, but it will be
        await sandbox.write_file(SANDBOX_CLI, f.read())
        # .write_file used `tee` which dropped execute permissions
        await sandbox.exec(["chmod", "+x", SANDBOX_CLI])
        print("DID IT!")


@asynccontextmanager
async def _open_executable(executable: str) -> AsyncIterator[BinaryIO]:
    """Open the executable file from the binaries package."""
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
                f"Tool support executable {executable_name} is required but not present. "
                f"To build it, run: python src/inspect_ai/tool/tool_support/build_within_container.py --arch {arch}"
            )


@asynccontextmanager
async def _open_executable_for_arch(
    arch: Architecture,
    with_browser: bool = False,
) -> AsyncIterator[tuple[str, BinaryIO]]:
    install_state = _get_install_state()

    print(f"{install_state=}")

    executable_name = _get_executable_name(
        arch, install_state == "edited", browser=with_browser
    )

    # 3.1. Local Executable Check
    try:
        async with _open_executable(executable_name) as f:
            print(f"found {executable_name}")
            yield executable_name, f
            return
    except (FileNotFoundError, ModuleNotFoundError):
        if install_state == "pypi":
            raise PrerequisiteError(
                f"Tool support executable {executable_name} is missing from the PyPI package installation. "
                "This indicates a problem with the package. Please reinstall inspect_ai."
            )

    # Only let one task at a time try to resolve the file.
    async with concurrency(executable_name, 1):
        # 3.2. S3 Download Attempt
        if install_state == "main":
            if await _download_from_s3(executable_name, arch):
                async with _open_executable(executable_name) as f:
                    print(f"downloaded {executable_name} from s3")
                    yield executable_name, f
                    return
            # TODO: One could argue that we should not fall through here. If they
            # haven't made any edits to tool_support, they 100% should be able to
            # download from S3. This scenario is similar to the pypi error just above.

        # 3.4. Build it locally
        await _build_it(arch, executable_name)

        async with _open_executable(executable_name) as f:
            yield executable_name, f


def _get_tool_support_version() -> str:
    """Get the tool support version from VERSION file."""
    import importlib.resources

    try:
        # Try to read from the package first
        with (
            importlib.resources.files("inspect_ai.tool")
            .joinpath("tool_support/VERSION.txt")
            .open() as f
        ):
            return f.read().strip()
    except Exception:
        # Fallback: try to read from filesystem for git/editable installs
        try:
            package_path = Path(inspect_ai.__file__).parent
            version_file = package_path / "tool" / "tool_support" / "VERSION.txt"
            if version_file.exists():
                return version_file.read_text().strip()
        except Exception:
            pass

        # Ultimate fallback - version 1
        return "1"


def _get_executable_name(arch: Architecture, dev: bool, browser: bool) -> str:
    return config_to_filename(
        BuildConfig(
            arch=arch,
            version=int(_get_tool_support_version()),
            browser=browser,
            suffix="dev" if dev else None,
        )
    )


async def _download_from_s3(filename: str, arch: Architecture) -> bool:
    """Download executable from S3. Returns True if successful, False otherwise.

    Handles expected failures (404 - not yet promoted) silently.
    Logs unexpected failures but doesn't raise exceptions.
    """
    _prompt_user_action(
        f"Executable '{filename}' not found locally. Download from S3?",
        filename,
        arch,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Download the executable
            response = await client.get(f"{BUCKET_BASE_URL}/{filename}")
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
    import importlib.metadata
    from importlib.metadata import PackageNotFoundError

    package_path = Path(inspect_ai.__file__).parent

    try:
        # Use importlib.metadata to get package information
        dist = importlib.metadata.distribution("inspect-ai")

        # If there are editable install indicators, it's not a PyPI install
        if dist.files:
            for file_path in dist.files:
                if file_path.suffix == ".egg-link" or "direct_url.json" in str(
                    file_path
                ):
                    # Not a PyPI install, check for changes
                    return _check_for_changes()

        # Check if in site-packages and without source files (indicating PyPI wheel)
        if "site-packages" in str(package_path):
            build_script_path = (
                package_path.parent.parent
                / "inspect_ai"
                / "tool"
                / "tool_support"
                / "build_within_container.py"
            )
            # PyPI installs don't include source files like build scripts
            if not build_script_path.exists():
                return "pypi"

        # Not a PyPI install, check for changes
        return _check_for_changes()

    except PackageNotFoundError:
        # Fallback: if in site-packages and no build script, likely PyPI
        if "site-packages" in str(package_path):
            build_script_path = (
                package_path.parent.parent
                / "inspect_ai"
                / "tool"
                / "tool_support"
                / "build_within_container.py"
            )
            if not build_script_path.exists():
                return "pypi"

        # Not a PyPI install, check for changes
        return _check_for_changes()


def _check_for_changes() -> Literal["main", "edited"]:
    """Check if there are changes to tool support files relative to main.

    Returns:
        "main": No changes to tool support files relative to main branch,
            or git is not available/functioning (assumes stable version)
        "edited": Changes detected to tool support files - either
            uncommitted changes (staged/unstaged) or committed changes relative
            to main branch
    """
    possible_git_root = Path(__file__).parent.parent.parent.parent

    print(f"Checking for changes {possible_git_root=}")
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
            cwd=possible_git_root,
        )
        if result.returncode != 0:
            print(f"git rev-parse failed {result}")
            # Not a git repo, assume main for safety
            return "main"

        # Check for staged or unstaged changes to relevant paths
        paths_to_check = [
            "src/inspect_ai/tool/tool_support",
            "VERSION.txt",
        ]

        for path in paths_to_check:
            # Check for uncommitted changes (staged + unstaged)
            result = subprocess.run(
                ["git", "status", "--porcelain", path],
                capture_output=True,
                text=True,
                check=False,
                cwd=possible_git_root,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "edited"

            # Check for committed changes relative to main
            result = subprocess.run(
                ["git", "diff", "main", "--quiet", path],
                capture_output=True,
                text=True,
                check=False,
                cwd=possible_git_root,
            )
            if result.returncode != 0:
                return "edited"

        return "main"

    except (subprocess.SubprocessError, FileNotFoundError):
        # If git commands fail, assume main for safety
        return "main"
