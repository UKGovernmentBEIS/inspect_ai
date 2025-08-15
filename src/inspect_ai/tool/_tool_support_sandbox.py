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
    "x86_64",  # 64-bit Intel/AMD
    "aarch64",  # 64-bit ARM
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

    async with _open_executable_for_arch(
        "arm64" if info["architecture"] == "aarch64" else "amd64"
    ) as f:
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
        "x86_64": "x86_64",
        "amd64": "x86_64",  # Windows/Docker often reports as amd64
        "aarch64": "aarch64",
        "arm64": "aarch64",  # macOS/Docker often reports as arm64
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


async def _go_get_it(arch: Architecture, executable: str) -> None:
    installation_type = _detect_installation_type()

    if installation_type == "pypi":
        # Case 1: PyPI package installation - executables should be bundled
        raise PrerequisiteError(
            f"Tool support executable {executable} is missing from the PyPI package installation. "
            "This indicates a problem with the package. Please reinstall inspect_ai."
        )

    elif installation_type == "git":
        # Case 2: Git reference installation - download from external source
        # TODO: This is where we'll download pre-built binaries from GitHub releases or CDN
        # based on commit hash or version tag for exact version matching
        raise NotImplementedError(
            f"Tool support executable {executable} is not available for git reference installations. "
            "Pre-built binary hosting solution is not yet implemented. "
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
    """Detect the type of installation and return appropriate case identifier."""
    package_path = Path(inspect_ai.__file__).parent

    # TODO: FRAGILE DETECTION METHOD - This approach is not robust!
    # The "site-packages" string matching will fail in many scenarios:
    # - Alternative package managers (conda, poetry, uv, etc.)
    # - Custom virtual environments with different directory structures
    # - Corporate/enterprise Python distributions
    # - System package managers (apt, yum, brew)
    # - Non-standard PYTHONPATH configurations
    # - Docker containers with unusual layouts
    #
    # Consider more robust alternatives:
    # - Check for .egg-link files (editable installs)
    # - Use importlib.metadata to examine package metadata
    # - Combine multiple heuristics with fallback strategies
    # - Examine filesystem structure more intelligently
    #
    # For now, this works for common pip-based installations but will
    # need improvement for production robustness.

    # Check if we're in site-packages (indicates pip install, not editable)
    if "site-packages" in str(package_path):
        # This could be either Case 1 (PyPI) or Case 2 (git reference)
        # Both get installed to site-packages, but git installs include source files
        build_script_path = (
            package_path.parent.parent
            / "inspect_tool_support"
            / "build_within_container.py"
        )

        if build_script_path.exists():
            return "git"  # Case 2: pip install git+https://github.com/...
        else:
            return "pypi"  # Case 1: pip install inspect-ai (wheel package)

    else:
        # Not in site-packages, so this is likely an editable install
        return "editable"  # Case 3: pip install -e . or pip install -e git+...
