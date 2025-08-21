from logging import getLogger
from pathlib import Path
from typing import Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from ._config import MCPServerConfigHTTP
from ._remote import MCPServerRemote
from ._types import MCPServer

logger = getLogger(__name__)


def mcp_server_sse(
    *,
    name: str | None = None,
    url: str,
    execution: Literal["local", "remote"] = "local",
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    """MCP Server (SSE).

    SSE interface to MCP server.  Use this for MCP servers available via a URL endpoint.

    NOTE: The SEE interface has been [deprecated](https://mcp-framework.com/docs/Transports/sse/)
    in favor of `mcp_server_http()` for MCP servers at URL endpoints.

    Args:
        name: Human readable name for the server (defaults to `url` if not specified)
        url: URL to remote server
        execution: Where to execute tool call ("local" for within the Inspect process, "remote" for execution by the model provider -- note this is currently only supported by OpenAI and Anthropic).
        authorization: OAuth Bearer token for authentication with server.
        headers: Headers to send server (typically authorization is included here)
        timeout: Timeout for HTTP operations
        sse_read_timeout: How long (in seconds) the client will wait for a new
            event before disconnecting.

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._local import create_server_sse

    name = name or url
    headers = _resolve_headers(authorization, headers)

    if execution == "local":
        return create_server_sse(
            name=name,
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
        )
    elif execution == "remote":
        return MCPServerRemote(
            MCPServerConfigHTTP(type="sse", name=name, url=url, headers=headers)
        )
    else:
        raise ValueError(f"Unexpected execution type: {execution}")


def mcp_server_http(
    *,
    name: str | None = None,
    url: str,
    execution: Literal["local", "remote"] = "local",
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer:
    """MCP Server (SSE).

    HTTP interface to MCP server. Use this for MCP servers available via a URL endpoint.

    Args:
        name: Human readable name for the server (defaults to `url` if not specified)
        url: URL to remote server
        execution: Where to execute tool call ("local" for within the Inspect process, "remote" for execution by the model provider -- note this is currently only supported by OpenAI and Anthropic).
        authorization: OAuth Bearer token for authentication with server.
        headers: Headers to send server (typically authorization is included here)
        timeout: Timeout for HTTP operations
        sse_read_timeout: How long (in seconds) the client will wait for a new
            event before disconnecting.

    Returns:
        McpClient: Client for MCP Server
    """
    verfify_mcp_package()
    from ._local import create_server_streamablehttp

    name = name or url
    headers = _resolve_headers(authorization, headers)

    if execution == "local":
        return create_server_streamablehttp(
            name=name,
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
        )
    elif execution == "remote":
        return MCPServerRemote(
            MCPServerConfigHTTP(type="http", name=name, url=url, headers=headers)
        )
    else:
        raise ValueError(f"Unexpected execution type: {execution}")


def mcp_server_stdio(
    *,
    name: str | None = None,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> MCPServer:
    """MCP Server (Stdio).

    Stdio interface to MCP server. Use this for MCP servers that run locally.

    Args:
        name: Human readable name for the server (defaults to `command` if not specified)
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
    from ._local import create_server_stdio

    return create_server_stdio(
        name=name or " ".join([command] + args),
        command=command,
        args=args,
        cwd=cwd,
        env=env,
    )


def mcp_server_sandbox(
    *,
    name: str | None = None,
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
        name: Human readable name for server (defaults to `command` with args if not specified).
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
    from ._local import create_server_sandbox

    return create_server_sandbox(
        name=name or " ".join([command] + args),
        command=command,
        args=args,
        cwd=cwd,
        env=env,
        sandbox=sandbox,
        timeout=timeout,
    )


def verfify_mcp_package() -> None:
    FEATURE = "MCP tools"
    PACKAGE = "mcp"
    MIN_VERSION = "1.12.3"

    # verify we have the package
    try:
        import mcp  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)


def _resolve_headers(
    authorization: str | None = None, headers: dict[str, str] | None = None
) -> dict[str, str] | None:
    if authorization is None and headers is None:
        return None
    if headers is None:
        headers = dict()
    if authorization is not None:
        headers["Authorization"] = f"Bearer {authorization}"
    return headers
