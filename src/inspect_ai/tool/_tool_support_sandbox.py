from typing import TypedDict, cast

from inspect_ai.util._sandbox.environment import SandboxEnvironment


class ContainerOSInfo(TypedDict, total=False):
    """Type definition for container OS detection results."""

    os: str
    distribution: str
    version: str
    version_info: str
    architecture: str
    uname: str


async def inject_tool_support_code(sandbox: SandboxEnvironment) -> None:
    foo = await _detect_linux(sandbox)
    print(f"The sandbox is running {foo}")


async def _sandbox_exec(sandbox: SandboxEnvironment, command: str) -> str:
    """Execute a command in the container and return the output."""
    result = await sandbox.exec(["sh", "-c", command], timeout=30)
    if not result.success:
        raise RuntimeError(
            f"Error executing command {' '.join(command)}: {result.stderr}"
        )
    return result.stdout.strip()


async def _detect_architecture(sandbox: SandboxEnvironment) -> str:
    """Detect the architecture of the container."""
    arch_cmd = """
if command -v uname >/dev/null 2>&1; then
    uname -m
else
    echo "unknown"
fi
"""

    arch_output = await _sandbox_exec(sandbox, arch_cmd)
    if not arch_output:
        return "Unknown (uname not available)"

    arch = arch_output.lower()
    arch_mapping = {
        "x86_64": "x86_64 (amd64)",
        "amd64": "x86_64 (amd64)",
        "aarch64": "aarch64 (arm64)",
        "arm64": "aarch64 (arm64)",
        "armv7l": "armv7l (armhf)",
        "armhf": "armv7l (armhf)",
        "i386": "i386",
        "i686": "i386",
    }

    return arch_mapping.get(arch, arch)


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


# async def _detect_windows(sandbox: SandboxEnvironment) -> ContainerOSInfo | None:
#     """Detect Windows OS information."""
#     # Check if cmd is available
#     if not await _sandbox_exec(
#         sandbox, "command -v cmd >/dev/null 2>&1 && echo 'found'"
#     ):
#         return None

#     result = {"os": "Windows"}

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

#     # Get architecture
#     arch_cmd = 'powershell -Command "echo $env:PROCESSOR_ARCHITECTURE" 2>/dev/null'
#     arch_output = await _sandbox_exec(sandbox, arch_cmd)
#     if arch_output:
#         result["architecture"] = arch_output
#     else:
#         result["architecture"] = "Unknown (PowerShell not available)"

#     return cast(ContainerOSInfo, result)


# async def _detect_macos(sandbox: SandboxEnvironment) -> ContainerOSInfo | None:
#     """Detect macOS information."""
#     if not await _sandbox_exec(
#         sandbox, "command -v sw_vers >/dev/null 2>&1 && echo 'found'"
#     ):
#         return None

#     result = {"os": "macOS"}

#     sw_vers_output = await _sandbox_exec(sandbox, "sw_vers")
#     if sw_vers_output:
#         result["version_info"] = sw_vers_output

#     result["architecture"] = await _detect_architecture(sandbox)

#     return cast(ContainerOSInfo, result)
