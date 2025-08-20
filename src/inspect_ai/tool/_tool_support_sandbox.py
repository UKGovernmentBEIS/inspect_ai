import subprocess
import sys
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Literal, TypeAlias, TypedDict

from rich.prompt import Prompt

import inspect_ai
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import input_screen
from inspect_ai.util._sandbox.environment import SandboxEnvironment

Architecture: TypeAlias = Literal[
    "amd64",  # 64-bit Intel/AMD
    "arm64",  # 64-bit ARM
]


class SupportedContainerOSInfo(TypedDict, total=False):
    os: Literal["Linux"]
    distribution: Literal["Ubuntu", "Debian", "Kali Linux", "Debian-based"]
    version: str
    version_info: str
    architecture: Architecture
    uname: str


# TODO: Currently, this logic relies on a specific file existing at a specific path
# this may need to be enhanced to use a dynamic predicate instead. otherwise, how
# would we work on os's with a different directory structure?
SANDBOX_CLI = "/opt/inspect-tool-support"


async def inject_tool_support_code(sandbox: SandboxEnvironment) -> None:
    info = await _detect_sandbox_os(sandbox)

    async with _open_executable_for_arch(info["architecture"]) as f:
        await sandbox.write_file(SANDBOX_CLI, f.read())
        # .write_file used `tee` which dropped execute permissions
        await sandbox.exec(["chmod", "+x", SANDBOX_CLI])


async def _detect_sandbox_os(sandbox: SandboxEnvironment) -> SupportedContainerOSInfo:
    """Detect OS information using standard platform.uname() system values."""
    # First, determine the system type using uname -s (similar to platform.uname().system)
    system_cmd = """
if command -v uname >/dev/null 2>&1; then
    uname -s
else
    echo "unknown"
fi
"""

    system_output = await _sandbox_exec(sandbox, system_cmd)
    system = system_output.strip() if system_output else "unknown"

    # Only Linux is supported for tool injection
    if system == "Linux":
        return await _detect_linux(sandbox)
    else:
        raise NotImplementedError(
            f"Tool support injection is not implemented for OS: {system}. "
            "Only Linux containers are currently supported."
        )


async def _sandbox_exec(sandbox: SandboxEnvironment, command: str) -> str:
    """Execute a command in the container and return the output."""
    result = await sandbox.exec(["sh", "-c", command], timeout=30)
    if not result.success:
        raise RuntimeError(
            f"Error executing command {' '.join(command)}: {result.stderr}"
        )
    return result.stdout.strip()


async def _detect_architecture(sandbox: SandboxEnvironment) -> Architecture:
    """Detect the architecture of the container using standard platform.uname() machine values."""
    arch_cmd = """
if command -v uname >/dev/null 2>&1; then
    uname -m
else
    echo "unknown"
fi
"""

    arch_output = await _sandbox_exec(sandbox, arch_cmd)
    if not arch_output or arch_output == "unknown":
        raise RuntimeError("Unable to determine sandbox architecture")

    arch = arch_output.lower()
    arch_mapping: dict[str, Architecture] = {
        "x86_64": "amd64",
        "amd64": "amd64",  # Windows/Docker often reports as amd64
        "aarch64": "arm64",
        "arm64": "arm64",  # macOS/Docker often reports as arm64
    }

    if arch not in arch_mapping:
        raise NotImplementedError(f"Architecture {arch} is not supported.")
    return arch_mapping[arch]


async def _detect_linux(sandbox: SandboxEnvironment) -> SupportedContainerOSInfo:
    """Detect Linux distribution information."""
    # Check /etc/os-release first
    os_release_cmd = """
if [ -f /etc/os-release ]; then
    cat /etc/os-release
else
    echo "not_found"
fi
"""

    architecture = await _detect_architecture(sandbox)
    os_release_output = await _sandbox_exec(sandbox, os_release_cmd)
    if os_release_output and os_release_output != "not_found":
        os_info = {
            key: value.strip('"')
            for line in os_release_output.split("\n")
            if "=" in line
            for key, value in [line.split("=", 1)]
        }

        distro_id = os_info.get("ID", "").lower()

        return SupportedContainerOSInfo(
            os="Linux",
            distribution=(
                "Ubuntu"
                if distro_id == "ubuntu"
                else "Debian"
                if distro_id == "debian"
                else "Kali Linux"
            ),
            version=os_info.get("VERSION", "Unknown"),
            architecture=architecture,
        )

    # Fallback: check for Kali version file
    kali_version = await _sandbox_exec(
        sandbox, "[ -f /etc/kali_version ] && cat /etc/kali_version"
    )
    if kali_version:
        return SupportedContainerOSInfo(
            os="Linux",
            distribution="Kali Linux",
            version=kali_version,
            architecture=architecture,
        )

    # Fallback: check for Debian version file
    debian_version = await _sandbox_exec(
        sandbox, "[ -f /etc/debian_version ] && cat /etc/debian_version"
    )
    if debian_version:
        return SupportedContainerOSInfo(
            os="Linux",
            distribution="Debian-based",
            version=debian_version,
            architecture=architecture,
        )

    # Last resort: raise error if OS/distribution could not be determined
    raise RuntimeError("Could not determine OS/distribution")


@asynccontextmanager
async def _open_executable(executable: str) -> AsyncIterator[BinaryIO]:
    """Open the executable file from the binaries package."""
    with resources.path("inspect_ai.binaries", executable) as executable_path:
        with open(executable_path, "rb") as f:
            yield f


@asynccontextmanager
async def _open_executable_for_arch(arch: Architecture) -> AsyncIterator[BinaryIO]:
    """Resolve and provide access to the executable file."""
    # Build the executable filename based on architecture
    executable = f"inspect-tool-support-{arch}"

    # Check if executable exists in the binaries package
    try:
        async with _open_executable(executable) as f:
            yield f
            return
    except (FileNotFoundError, ModuleNotFoundError):
        # Executable doesn't exist, handle based on installation type
        pass

    await _go_get_it(arch, executable)
    async with _open_executable(executable) as f:
        yield f


def _get_tool_support_version() -> str:
    """Get the tool support version from VERSION file."""
    import importlib.resources

    try:
        # Try to read from the package first
        with (
            importlib.resources.files("inspect_ai.tool")
            .joinpath("_tool_support_version.txt")
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
    """Get the versioned executable name for the given architecture."""
    version = _get_tool_support_version()
    return f"inspect-tool-support-{arch}-v{version}"


async def _download_from_github_releases(arch: Architecture) -> None:
    """Download the versioned executable from GitHub releases."""
    from pathlib import Path

    import httpx

    versioned_executable = _get_versioned_executable_name(arch)

    # GitHub release URL pattern
    repo_url = "https://api.github.com/repos/UKGovernmentBEIS/inspect_ai/releases"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get releases to find the one with our version
            response = await client.get(repo_url)
            response.raise_for_status()
            releases = response.json()

            # Look for a release that contains our versioned executable
            download_url = None
            for release in releases:
                for asset in release.get("assets", []):
                    if asset["name"] == versioned_executable:
                        download_url = asset["browser_download_url"]
                        break
                if download_url:
                    break

            if not download_url:
                raise RuntimeError(
                    f"Executable {versioned_executable} not found in any GitHub release"
                )

            # Download the executable
            response = await client.get(download_url)
            response.raise_for_status()

            # Save to binaries directory
            binaries_path = Path(inspect_ai.__file__).parent / "binaries"
            binaries_path.mkdir(exist_ok=True)

            # Save with original non-versioned name for compatibility
            executable_path = binaries_path / f"inspect-tool-support-{arch}"
            executable_path.write_bytes(response.content)
            executable_path.chmod(0o755)

    except httpx.HTTPError as e:
        raise RuntimeError(f"HTTP error downloading executable: {e}")
    except Exception as e:
        raise RuntimeError(f"Error downloading executable: {e}")


async def _go_get_it(arch: Architecture, executable: str) -> None:
    installation_type = _detect_installation_type()

    if installation_type == "pypi":
        # Case 1: PyPI package installation - executables should be bundled
        raise PrerequisiteError(
            f"Tool support executable {executable} is missing from the PyPI package installation. "
            "This indicates a problem with the package. Please reinstall inspect_ai."
        )

    elif installation_type == "git":
        # Case 2: Git reference installation - download from GitHub releases
        try:
            await _download_from_github_releases(arch)
        except Exception as e:
            raise PrerequisiteError(
                f"Failed to download tool support executable for git installation: {e}\n"
                f"As a workaround, manually build with: python src/inspect_tool_support/build_within_container.py --arch {arch}"
            )

    elif installation_type == "editable":
        # Case 3: Editable installation - prompt user to build

        with input_screen():
            response = Prompt.ask(
                f"Tool support executable {executable} is missing. Build it now?",
                choices=["y", "n"],
                default="y",
                case_sensitive=False,
            )
            if response != "y":
                raise PrerequisiteError(
                    f"Tool support executable {executable} is required but not present. "
                    f"To build it, run: python src/inspect_tool_support/build_within_container.py --arch {arch}"
                )

        # Find the build script
        build_script_path = (
            Path(__file__).parent.parent.parent
            / "inspect_tool_support"
            / "build_within_container.py"
        )

        if not build_script_path.exists():
            raise FileNotFoundError(f"Build script not found at {build_script_path}")

        print(f"Building missing executable {executable} for {arch} architecture...")

        # Run the build script
        result = subprocess.run(
            [sys.executable, str(build_script_path), "--arch", arch],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to build executable {executable}: {result.stderr}"
            )

        print(f"Successfully built {executable}")
    else:
        raise PrerequisiteError(f"Unknown installation type: {installation_type}")


def _detect_installation_type() -> Literal["pypi", "git", "editable"]:
    """Detect the type of installation using multiple heuristics."""
    import importlib.metadata
    from importlib.metadata import PackageNotFoundError

    package_path = Path(inspect_ai.__file__).parent

    try:
        # Use importlib.metadata to get package information
        dist = importlib.metadata.distribution("inspect-ai")

        # Check if this is an editable install by looking for .egg-link or direct_url.json
        if dist.files:
            # Look for editable install indicators
            for file_path in dist.files:
                if file_path.suffix == ".egg-link" or "direct_url.json" in str(
                    file_path
                ):
                    # Check if it's an editable git install vs local editable
                    try:
                        direct_url_path = dist.locate_file("direct_url.json")
                        if direct_url_path and direct_url_path.exists():
                            import json

                            with open(str(direct_url_path)) as f:
                                direct_url = json.load(f)
                                if direct_url.get("vcs_info", {}).get("vcs") == "git":
                                    return "editable"  # pip install -e git+...
                    except Exception:
                        pass
                    return "editable"  # pip install -e .

        # Check if installed from git by examining the installation path and metadata
        if "site-packages" in str(package_path):
            # Look for source files that indicate git installation
            build_script_path = (
                package_path.parent.parent
                / "inspect_tool_support"
                / "build_within_container.py"
            )

            version_file_path = package_path / "tool" / "_tool_support_version.txt"

            # Git installations include the full source tree
            if build_script_path.exists() or version_file_path.exists():
                return "git"  # pip install git+https://github.com/...
            else:
                return "pypi"  # pip install inspect-ai (wheel)
        else:
            # Not in site-packages, likely development/editable install
            return "editable"

    except PackageNotFoundError:
        # Fallback to path-based detection if metadata unavailable
        if "site-packages" in str(package_path):
            # Check for source files indicating git install
            build_script_path = (
                package_path.parent.parent
                / "inspect_tool_support"
                / "build_within_container.py"
            )

            if build_script_path.exists():
                return "git"
            else:
                return "pypi"
        else:
            return "editable"
