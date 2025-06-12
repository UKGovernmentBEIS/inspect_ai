from logging import getLogger
from pathlib import Path
from typing import Any

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from ._types import MCPServer

logger = getLogger(__name__)


def mcp_server_sse(
    *,
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    """MCP Server (SSE).

    SSE interface to MCP server.  Use this for MCP servers available via a URL endpoint.

    Args:
        url: URL to remote server
        headers: Headers to send server (typically authorization is included here)
        timeout: Timeout for HTTP operations
        sse_read_timeout: How long (in seconds) the client will wait for a new
            event before disconnecting.

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._mcp import create_server_sse

    return create_server_sse(url, headers, timeout, sse_read_timeout)


def mcp_server_stdio(
    *,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> MCPServer:
    """MCP Server (Stdio).

    Stdio interface to MCP server. Use this for MCP servers that run locally.

    Args:
        command: The executable to run to start the server.
        args: Command line arguments to pass to the executable.
        env: The environment to use when spawning the process
            in addition to the platform specific set of default
            environment variables (e.g. "HOME", "LOGNAME", "PATH",
            "SHELL", "TERM", and "USER" for Posix-based systems).
        cwd: The working directory to use when spawning the process.

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._mcp import create_server_stdio

    return create_server_stdio(command, args, cwd, env)


def mcp_server_sandbox(
    *,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    sandbox: str | None = None,
    timeout: int | None = None,
) -> MCPServer:
    """MCP Server (Sandbox).

    Interface to MCP server running in an Inspect sandbox.

    Args:
        command: The executable to run to start the server.
        args: Command line arguments to pass to the executable.
        env: The environment to use when spawning the process
            in addition to the platform specific set of default
            environment variables (e.g. "HOME", "LOGNAME", "PATH",
            "SHELL", "TERM", and "USER" for Posix-based systems).
        cwd: The working directory to use when spawning the process.
        sandbox: The sandbox to use when spawning the process.
        timeout: Timeout (in seconds) for command.

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._mcp import create_server_sandbox

    return create_server_sandbox(command, args, cwd, env, sandbox, timeout)


def verfify_mcp_package() -> None:
    FEATURE = "MCP tools"
    PACKAGE = "mcp"
    MIN_VERSION = "1.9.4"

    # verify we have the package
    try:
        import mcp  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)
