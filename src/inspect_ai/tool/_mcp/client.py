from pathlib import Path
from typing import Any, Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from ._types import McpClient


def mcp_sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    memoize: bool = True,
) -> McpClient:
    """SSE Model Context Protocol Client.

    SSE interface to MCP server
    (correponds to the [sse_client](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/sse.py) in
    the MCP Python SDK).

    Args:
        url: URL to remove server
        headers: Headers to send server (typically authorization is included here)
        timeout: Timeout for HTTP operations
        sse_read_timeout: How long (in seconds) the client will wait for a new
            event before disconnecting.
        memoize: Use/store a cached version of the client interface based on
            the parameters to `mcp_sse_client()`

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._mcp import McpSSEClient

    return McpSSEClient(url, headers, timeout, sse_read_timeout)


def mcp_stdio_client(
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
    memoize: bool = True,
) -> McpClient:
    """Stdio Model Context Protocol Client.

    Stdio interface to MCP server.
    (corresponds to the [stdio_client](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/client/stdio/__init__.py) in the MCP Python SDK).

    Args:
        command: The executable to run to start the server.
        args: Command line arguments to pass to the executable.
        env: The environment to use when spawning the process
            in addition to the platform specific set of default
            environment variables (e.g. "HOME", "LOGNAME", "PATH",
            "SHELL", "TERM", and "USER" for Posix-based systems).
        cwd: The working directory to use when spawning the process.
        encoding: The text encoding used when sending/receiving messages to the server
            (defaults to "utf-8").
        encoding_error_handler: The text encoding error handler.
            See <https://docs.python.org/3/library/codecs.html#codec-base-classes> for
            explanations of possible values
        memoize: Use/store a cached version of the client interface based on
            the parameters to `mcp_stdio_client()`

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._mcp import McpStdioClient

    return McpStdioClient(command, args, cwd, env, encoding, encoding_error_handler)


def mcp_sandbox_client(memoize: bool = True) -> McpClient:
    """Sandbox Model Context Protocol Client."

    Args:
        memoize: Use/store a cached version of the client interface based on
            the parameters to `mcp_sandbox_client()`

    Returns:
        McpClient: Client for MCP Serve:
    """
    verfify_mcp_package()
    from ._mcp import McpSandboxClient

    return McpSandboxClient()


def verfify_mcp_package() -> None:
    FEATURE = "MCP tools"
    PACKAGE = "mcp"
    MIN_VERSION = "1.6.0"

    # verify we have the package
    try:
        import mcp  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)
