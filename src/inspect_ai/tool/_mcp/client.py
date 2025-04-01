import hashlib
from contextvars import ContextVar
from copy import copy
from logging import getLogger
from pathlib import Path
from typing import Any, Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from ._types import McpClient

logger = getLogger(__name__)


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
    from ._mcp import create_sse_client

    # unique key for this call (keep url unhashed for logging)
    options = hashlib.sha256(
        f"{headers}{timeout}{sse_read_timeout}".encode()
    ).hexdigest()
    key = f"url={url},options={options}"

    # if we are memoizing then lookup in the cache first
    if memoize:
        client = cached_mcp_client(key)
        if client is not None:
            return client

    # create the client and add it to the cache if we are memoizing
    client = create_sse_client(url, headers, timeout, sse_read_timeout)
    if memoize:
        cache_mcp_client(key, client)

    # return the client
    return client


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
    from ._mcp import create_stdio_client

    # unique key for this call (keep command and args unhashed for logging)
    options = hashlib.sha256(
        f"{cwd}{env}{encoding}{encoding_error_handler}".encode()
    ).hexdigest()
    key = f"command={command},args={args},options={options}"

    # if we are memoizing then lookup in the cache first
    if memoize:
        client = cached_mcp_client(key)
        if client is not None:
            return client

    # create the client and add it to the cache if we are memoizing
    client = create_stdio_client(
        command, args, cwd, env, encoding, encoding_error_handler
    )
    if memoize:
        cache_mcp_client(key, client)

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


def init_mcp_clients() -> None:
    _mcp_clients.set({})


async def cleanup_mcp_clients() -> None:
    mcp_clients = copy(_mcp_clients.get())
    _mcp_clients.set({})
    for key, client in mcp_clients.items():
        try:
            await client.close()
        except Exception as ex:
            logger.warning(f"Unexpected error closing MCP client ({key}): {ex}")


def cache_mcp_client(key: str, client: McpClient) -> None:
    _mcp_clients.get()[key] = client


def cached_mcp_client(key: str) -> McpClient | None:
    # clean out context bound mcp clients before accessing the cache
    mcp_clients = _mcp_clients.get()
    for k in list(mcp_clients.keys()):
        if mcp_clients[k]._context_bound:
            del mcp_clients[k]

    # read from the cache
    return mcp_clients.get(key, None)


_mcp_clients: ContextVar[dict[str, McpClient]] = ContextVar("_mcp_clients", default={})
