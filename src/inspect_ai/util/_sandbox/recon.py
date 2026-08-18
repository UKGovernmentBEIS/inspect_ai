from typing import Literal, TypeAlias

from typing_extensions import TypedDict

from inspect_ai.util._sandbox.environment import SandboxEnvironment

Architecture: TypeAlias = Literal[
    "amd64",  # 64-bit Intel/AMD
    "arm64",  # 64-bit ARM
]

Libc: TypeAlias = Literal[
    "glibc",  # GNU libc (most distros)
    "musl",  # musl libc (Alpine and other musl-based distros)
]


class SupportedContainerOSInfo(TypedDict, total=False):
    os: Literal["Linux"]
    distribution: Literal["Ubuntu", "Debian", "Kali Linux", "Alpine", "Debian-based"]
    version: str
    version_info: str
    architecture: Architecture
    libc: Libc
    uname: str


async def detect_sandbox_os(sandbox: SandboxEnvironment) -> SupportedContainerOSInfo:
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
    result = await sandbox.exec(["sh", "-c", command], timeout=120)
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


async def _detect_libc(sandbox: SandboxEnvironment) -> Libc:
    """Detect whether the container uses musl or glibc.

    Lifted from inspect_swe's detect_sandbox_platform: the musl loader/libc is
    present at /lib/libc.musl-{arch}.so.1 on musl distros (e.g. Alpine); `ldd` on
    a musl system also reports "musl". The `||` chain short-circuits on the .so
    check so `ldd` is only consulted as a fallback, and its absence resolves to
    glibc.
    """
    musl_check_cmd = (
        "if [ -f /lib/libc.musl-x86_64.so.1 ] || "
        "[ -f /lib/libc.musl-aarch64.so.1 ] || "
        "ldd /bin/ls 2>&1 | grep -q musl; then "
        "echo 'musl'; else echo 'glibc'; fi"
    )
    return "musl" if await _sandbox_exec(sandbox, musl_check_cmd) == "musl" else "glibc"


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
    libc = await _detect_libc(sandbox)
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
                else "Alpine"
                if distro_id == "alpine"
                else "Kali Linux"
            ),
            version=os_info.get("VERSION", "Unknown"),
            architecture=architecture,
            libc=libc,
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
            libc=libc,
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
            libc=libc,
        )

    # Last resort: raise error if OS/distribution could not be determined
    raise RuntimeError("Could not determine OS/distribution")
