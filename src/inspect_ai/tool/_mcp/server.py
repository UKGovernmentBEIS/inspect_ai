import hashlib
import hmac
import os
from contextvars import ContextVar
from copy import copy
from logging import getLogger
from pathlib import Path
from typing import Any, Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from ._types import MCPServer

logger = getLogger(__name__)


# TODO: tool filtering and renaming


def mcp_server_sse(
    *,
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    memoize: bool = True,
) -> MCPServer:
    """MCP Server (SSE).

    SSE interface to MCP server.  Use this for MCP servers available via a URL endpoint.

    Args:
        url: URL to remote server
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
    from ._mcp import create_server_sse

    # unique key for this call (keep url unhashed for logging)
    options = hmac.new(
        key=os.urandom(16),
        msg=f"{headers}{timeout}{sse_read_timeout}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    key = f"url={url},options={options}"

    # if we are memoizing then lookup in the cache first
    if memoize:
        client = cached_mcp_server(key)
        if client is not None:
            return client

    # create the client and add it to the cache if we are memoizing
    client = create_server_sse(url, headers, timeout, sse_read_timeout)
    if memoize:
        cache_mcp_server(key, client)

    # return the client
    return client


def mcp_server_stdio(
    *,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
    memoize: bool = True,
) -> MCPServer:
    """MCP Server (Stdio).

    Stdio interface to MCP server.  Use this for MCP servers that run locally.

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
    from ._mcp import create_server_stdio

    # unique key for this call (keep command and args unhashed for logging)
    options = hmac.new(
        key=os.urandom(16),
        msg=f"{cwd}{env}{encoding}{encoding_error_handler}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    key = f"command={command},args={args},options={options}"

    # if we are memoizing then lookup in the cache first
    if memoize:
        client = cached_mcp_server(key)
        if client is not None:
            return client

    # create the client and add it to the cache if we are memoizing
    client = create_server_stdio(
        command, args, cwd, env, encoding, encoding_error_handler
    )
    if memoize:
        cache_mcp_server(key, client)

    # return the client
    return client


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


def init_mcp_servers() -> None:
    _mcp_servers.set({})


async def cleanup_mcp_servers() -> None:
    mcp_servers = copy(_mcp_servers.get())
    _mcp_servers.set({})
    for key, client in mcp_servers.items():
        try:
            await client.close()
        except Exception as ex:
            logger.warning(f"Unexpected error closing MCP client ({key}): {ex}")


def cache_mcp_server(key: str, server: MCPServer) -> None:
    _mcp_servers.get()[key] = server


def cached_mcp_server(key: str) -> MCPServer | None:
    # clean out context bound mcp clients before accessing the cache
    mcp_servers = _mcp_servers.get()
    for k in list(mcp_servers.keys()):
        if mcp_servers[k]._context_bound:
            del mcp_servers[k]

    # read from the cache
    return mcp_servers.get(key, None)


_mcp_servers: ContextVar[dict[str, MCPServer]] = ContextVar("_mcp_servers", default={})
