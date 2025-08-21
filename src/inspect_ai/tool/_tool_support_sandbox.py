import subprocess
import sys
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import AsyncIterator, BinaryIO

import httpx
from rich.prompt import Prompt

import inspect_ai
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import input_screen
from inspect_ai.util._sandbox._recon import Architecture, detect_sandbox_os
from inspect_ai.util._sandbox.environment import SandboxEnvironment

BUCKET_BASE_URL = "https://inspect-tool-support.s3.us-east-2.amazonaws.com"


# TODO: Currently, this logic relies on a specific file existing at a specific path
# this may need to be enhanced to use a dynamic predicate instead. otherwise, how
# would we work on os's with a different directory structure?
SANDBOX_CLI = "/opt/inspect-tool-support"


async def inject_tool_support_code(sandbox: SandboxEnvironment) -> None:
    info = await detect_sandbox_os(sandbox)

    async with _open_executable_for_arch(info["architecture"]) as (_, f):
        # TODO: The first tuple member, filename, isn't currently used, but it will be
        await sandbox.write_file(SANDBOX_CLI, f.read())
        # .write_file used `tee` which dropped execute permissions
        await sandbox.exec(["chmod", "+x", SANDBOX_CLI])


@asynccontextmanager
async def _open_executable(executable: str) -> AsyncIterator[BinaryIO]:
    """Open the executable file from the binaries package."""
    with resources.path("inspect_ai.binaries", executable) as executable_path:
        with open(executable_path, "rb") as f:
            yield f


@asynccontextmanager
async def _open_executable_for_arch(
    arch: Architecture,
) -> AsyncIterator[tuple[str, BinaryIO]]:
    is_pypi_install = _is_pypi_install()
    executable_name = _get_versioned_executable_name(arch)
    dev_executable_name = f"{executable_name}-dev"

    # 3.1. Local Executable Check - Check dev version first (unless it's PyPI)
    if not is_pypi_install:
        try:
            async with _open_executable(dev_executable_name) as f:
                yield dev_executable_name, f
                return
        except (FileNotFoundError, ModuleNotFoundError):
            pass

    # 3.1. Local Executable Check - Then check production version
    try:
        async with _open_executable(executable_name) as f:
            yield executable_name, f
            return
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    if is_pypi_install:
        raise PrerequisiteError(
            f"Tool support executable {executable_name} is missing from the PyPI package installation. "
            "This indicates a problem with the package. Please reinstall inspect_ai."
        )

    # 3.2. S3 Download Attempt - Try to download from S3
    try:
        await _download_from_s3(executable_name)
        async with _open_executable(executable_name) as f:
            yield executable_name, f
            return
    except Exception:
        # Download failure is expected when developers have bumped version
        # but new version hasn't been promoted to S3 yet. Proceed to build.
        pass

    # 3.3. User Build Prompt - Prompt user if S3 download failed
    with input_screen():
        response = Prompt.ask(
            "Executable not found. Build locally? (requires Docker)",
            choices=["y", "n"],
            default="y",
            case_sensitive=False,
        )
        if response != "y":
            raise PrerequisiteError(
                f"Tool support executable {dev_executable_name} is required but not present. "
                f"To build it, run: python src/inspect_tool_support/build_within_container.py --arch {arch} --dev"
            )

    # 3.4. Local Build Process - Build dev version locally
    await _build_it(arch, dev_executable_name)
    async with _open_executable(dev_executable_name) as f:
        yield dev_executable_name, f


def _get_tool_support_version() -> str:
    """Get the tool support version from VERSION file."""
    import importlib.resources

    try:
        # Try to read from the package first
        with (
            importlib.resources.files("inspect_ai.tool")
            .joinpath("tool_support_version.txt")
            .open() as f
        ):
            return f.read().strip()
    except Exception:
        # Fallback: try to read from filesystem for git/editable installs
        try:
            package_path = Path(inspect_ai.__file__).parent
            version_file = package_path / "tool" / "_tool_support_version.txt"
            if version_file.exists():
                return version_file.read_text().strip()
        except Exception:
            pass

        # Ultimate fallback - version 1
        return "1"


def _get_versioned_executable_name(arch: Architecture) -> str:
    """Get the base versioned executable name for the given architecture.

    This returns the production/S3 executable name. Development executables
    are created by appending "-dev" to this base name.
    """
    return f"inspect-tool-support-{arch}-v{_get_tool_support_version()}"


async def _download_from_s3(filename: str) -> None:
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

    except httpx.HTTPError as e:
        raise RuntimeError(f"HTTP error downloading executable: {e}")
    except Exception as e:
        raise RuntimeError(f"Error downloading executable: {e}")


async def _build_it(arch: Architecture, dev_executable_name: str) -> None:
    # Find the build script
    build_script_path = (
        Path(__file__).parent.parent.parent
        / "inspect_tool_support"
        / "build_within_container.py"
    )

    if not build_script_path.exists():
        raise FileNotFoundError(f"Build script not found at {build_script_path}")

    print(f"Building missing executable {dev_executable_name}...")

    # Run the build script
    subprocess.run(
        [sys.executable, str(build_script_path), "--arch", arch, "--dev"],
        capture_output=True,
        text=True,
        check=True,
    )

    print(f"Successfully built {dev_executable_name}")


def _is_pypi_install() -> bool:
    """Detect if this is a PyPI installation (wheel from PyPI, not git or editable)."""
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
                    return False

        # Check if in site-packages and without source files (indicating PyPI wheel)
        if "site-packages" in str(package_path):
            build_script_path = (
                package_path.parent.parent
                / "inspect_tool_support"
                / "build_within_container.py"
            )
            # PyPI installs don't include source files like build scripts
            return not build_script_path.exists()

        return False

    except PackageNotFoundError:
        # Fallback: if in site-packages and no build script, likely PyPI
        if "site-packages" in str(package_path):
            build_script_path = (
                package_path.parent.parent
                / "inspect_tool_support"
                / "build_within_container.py"
            )
            return not build_script_path.exists()

        return False
