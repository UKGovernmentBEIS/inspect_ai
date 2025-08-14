from importlib import resources
from typing import Literal, TypedDict, cast

from inspect_ai.util._sandbox.environment import SandboxEnvironment


class ContainerOSInfo(TypedDict, total=False):
    """Type definition for container OS detection results."""

    # Standard platform.uname() system values
    os: (
        Literal["Linux", "Windows", "Darwin", ""] | str
    )  # Allow other system names as fallback

    # Linux distribution names (only relevant for Linux systems)
    distribution: (
        Literal["Ubuntu", "Debian", "Kali Linux", "Debian-based", "Other/Unknown"] | str
    )  # Allow "Other Linux ({name})" pattern

    version: str
    version_info: str

    # Standard platform.uname() machine values
    architecture: (
        Literal[
            "x86_64",  # 64-bit Intel/AMD
            "aarch64",  # 64-bit ARM
            "armv7l",  # 32-bit ARM
            "i386",  # 32-bit Intel
            "",  # Empty when undetermined
        ]
        | str
    )  # Allow other architectures as fallback

    uname: str


# TODO: Currently, this logic relies on a specific file existing at a specific path
# this may need to be enhanced to use a dynamic predicate instead. otherwise, how
# would we work on os's with a different directory structure?
SANDBOX_CLI = "/opt/inspect-tool-support"


async def inject_tool_support_code(sandbox: SandboxEnvironment) -> None:
    info = await _detect_os(sandbox)
    assert info["os"] == "Linux", f"Unexpected os: {info['os']}"
    assert info["architecture"] in ("aarch64", "x86_64"), (
        f"Unexpected architecture: {info['architecture']}"
    )
    executable = (
        "inspect-tool-support-arm64"
        if info["architecture"] == "aarch64"
        else "inspect-tool-support-amd64"
    )

    with resources.path("inspect_ai.binaries", executable) as executable_path:
        with open(executable_path, "rb") as f:
            await sandbox.write_file(SANDBOX_CLI, f.read())
            # .write_file used `tee` which dropped execute permissions
            await sandbox.exec(["chmod", "+x", SANDBOX_CLI])


async def _detect_os(sandbox: SandboxEnvironment) -> ContainerOSInfo:
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

    # Normalize system name to match platform.uname() values
    if system == "Linux":
        return await _detect_linux(sandbox)
    elif system == "Darwin":
        return await _detect_darwin(sandbox)
    elif (
        system.startswith("CYGWIN")
        or system.startswith("MINGW")
        or system == "Windows_NT"
    ):
        return await _detect_windows(sandbox)
    else:
        # Fallback for unknown systems
        result = {
            "os": system if system != "unknown" else "",
            "architecture": await _detect_architecture(sandbox),
        }

        # Try to get some version info
        uname_output = await _sandbox_exec(sandbox, "uname -a 2>/dev/null")
        if uname_output:
            result["uname"] = uname_output

        return cast(ContainerOSInfo, result)


async def _sandbox_exec(sandbox: SandboxEnvironment, command: str) -> str:
    """Execute a command in the container and return the output."""
    result = await sandbox.exec(["sh", "-c", command], timeout=30)
    if not result.success:
        raise RuntimeError(
            f"Error executing command {' '.join(command)}: {result.stderr}"
        )
    return result.stdout.strip()


async def _detect_architecture(sandbox: SandboxEnvironment) -> str:
    """Detect the architecture of the container using standard platform.uname() machine values."""
    arch_cmd = """
if command -v uname >/dev/null 2>&1; then
    uname -m
else
    echo "unknown"
fi
"""

    arch_output = await _sandbox_exec(sandbox, arch_cmd)
    if not arch_output:
        return ""

    arch = arch_output.lower()
    # Normalize to standard platform.uname() machine values
    arch_mapping = {
        "x86_64": "x86_64",
        "amd64": "x86_64",  # Windows/Docker often reports as amd64
        "aarch64": "aarch64",
        "arm64": "aarch64",  # macOS/Docker often reports as arm64
        "armv7l": "armv7l",
        "armhf": "armv7l",
        "i386": "i386",
        "i686": "i386",
    }

    return arch_mapping.get(arch, arch if arch != "unknown" else "")


async def _detect_linux(sandbox: SandboxEnvironment) -> ContainerOSInfo:
    """Detect Linux distribution information."""
    result = {"os": "Linux"}

    # Check /etc/os-release first
    os_release_cmd = """
if [ -f /etc/os-release ]; then
    cat /etc/os-release
else
    echo "not_found"
fi
"""

    os_release_output = await _sandbox_exec(sandbox, os_release_cmd)
    if os_release_output and os_release_output != "not_found":
        # Parse os-release file
        os_info = {}
        for line in os_release_output.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                os_info[key] = value.strip('"')

        distro_id = os_info.get("ID", "").lower()
        name = os_info.get("NAME", "Unknown")
        version = os_info.get("VERSION", "Unknown")

        if distro_id == "ubuntu":
            result["distribution"] = "Ubuntu"
        elif distro_id == "debian":
            result["distribution"] = "Debian"
        elif distro_id == "kali":
            result["distribution"] = "Kali Linux"
        else:
            result["distribution"] = f"Other Linux ({name})"

        result["version"] = version
        result["architecture"] = await _detect_architecture(sandbox)
        return cast(ContainerOSInfo, result)

    # Fallback: check for Kali version file
    kali_version = await _sandbox_exec(
        sandbox, "[ -f /etc/kali_version ] && cat /etc/kali_version"
    )
    if kali_version:
        result["distribution"] = "Kali Linux"
        result["version"] = kali_version
        result["architecture"] = await _detect_architecture(sandbox)
        return cast(ContainerOSInfo, result)

    # Fallback: check for Debian version file
    debian_version = await _sandbox_exec(
        sandbox, "[ -f /etc/debian_version ] && cat /etc/debian_version"
    )
    if debian_version:
        result["distribution"] = "Debian-based"
        result["version"] = debian_version
        result["architecture"] = await _detect_architecture(sandbox)
        return cast(ContainerOSInfo, result)

    # Last resort: try uname
    result["distribution"] = "Other/Unknown"
    result["architecture"] = await _detect_architecture(sandbox)

    uname_output = await _sandbox_exec(sandbox, "uname -a 2>/dev/null")
    if uname_output:
        result["uname"] = uname_output
    else:
        result["uname"] = "Could not determine OS"

    return cast(ContainerOSInfo, result)


async def _detect_windows(sandbox: SandboxEnvironment) -> ContainerOSInfo:
    """Detect Windows OS information."""
    result = {"os": "Windows"}

    # Try to get version info
    version_cmd = "cmd /c ver 2>/dev/null"
    version_output = await _sandbox_exec(sandbox, version_cmd)
    if version_output:
        result["version"] = version_output
    else:
        # Try PowerShell version
        ps_cmd = 'powershell -Command "$PSVersionTable.PSVersion" 2>/dev/null'
        ps_output = await _sandbox_exec(sandbox, ps_cmd)
        if ps_output:
            result["version"] = ps_output

    result["architecture"] = await _detect_architecture(sandbox)
    return cast(ContainerOSInfo, result)


async def _detect_darwin(sandbox: SandboxEnvironment) -> ContainerOSInfo:
    """Detect macOS/Darwin information."""
    result = {"os": "Darwin"}

    # Try to get macOS version info
    sw_vers_output = await _sandbox_exec(sandbox, "sw_vers 2>/dev/null")
    if sw_vers_output:
        result["version_info"] = sw_vers_output

    result["architecture"] = await _detect_architecture(sandbox)
    return cast(ContainerOSInfo, result)


# Alternative implementation using conditional detection:
# async def _detect_windows_conditional(sandbox: SandboxEnvironment) -> ContainerOSInfo | None:
#     """Detect Windows OS information - conditional approach."""
#     # Check if cmd is available
#     if not await _sandbox_exec(
#         sandbox, "command -v cmd >/dev/null 2>&1 && echo 'found'"
#     ):
#         return None

#     result = {"os": "Windows"}  # Uses standard platform.uname() system value

#     # Try to get version info
#     version_cmd = "cmd /c ver 2>/dev/null"
#     version_output = await _sandbox_exec(sandbox, version_cmd)
#     if version_output:
#         result["version"] = version_output
#     else:
#         # Try PowerShell version
#         ps_cmd = 'powershell -Command "$PSVersionTable.PSVersion" 2>/dev/null'
#         ps_output = await _sandbox_exec(sandbox, ps_cmd)
#         if ps_output:
#             result["version"] = ps_output

#     result["architecture"] = await _detect_architecture(sandbox)  # Returns standard machine values
#     return cast(ContainerOSInfo, result)


# async def _detect_macos_conditional(sandbox: SandboxEnvironment) -> ContainerOSInfo | None:
#     """Detect macOS information - conditional approach."""
#     if not await _sandbox_exec(
#         sandbox, "command -v sw_vers >/dev/null 2>&1 && echo 'found'"
#     ):
#         return None

#     result = {"os": "Darwin"}  # Uses standard platform.uname() system value (Darwin, not macOS)

#     sw_vers_output = await _sandbox_exec(sandbox, "sw_vers")
#     if sw_vers_output:
#         result["version_info"] = sw_vers_output

#     result["architecture"] = await _detect_architecture(sandbox)  # Returns standard machine values
#     return cast(ContainerOSInfo, result)
