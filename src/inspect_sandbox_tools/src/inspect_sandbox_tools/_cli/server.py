#!/usr/bin/env python3
import asyncio
import json
import os
import signal
import socket
import sys

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import Success, async_dispatch, method

from inspect_sandbox_tools._util.constants import (
    SERVER_DIR,
    SERVER_DIR_ENV,
    SERVER_PID_PATH,
    SHUTDOWN_STATUS_PATH,
    SOCKET_PATH,
    ensure_private_server_dir,
    read_private_text,
    write_private_text,
)
from inspect_sandbox_tools._util.load_tools import load_tools

_shutdown_errors: list[str] = []
_shutdown_complete = False
_HTTP_SHUTDOWN_TIMEOUT = 5
_SHUTDOWN_STATUS_TMP_PATH = SHUTDOWN_STATUS_PATH.with_name(
    f"{SHUTDOWN_STATUS_PATH.name}.tmp"
)

# When running as a PyInstaller bundle, the bootloader prepends the bundle's
# lib directory to LD_LIBRARY_PATH so the daemon's native dependencies can be
# loaded, and saves the user's original value to LD_LIBRARY_PATH_ORIG. (This
# applies to --onedir bundles too: _MEIPASS points at the on-disk bundle dir.)
# By the time this module is imported every C extension the daemon needs has
# already been resolved, so we sanitize the environment that propagates into
# every subprocess we spawn (exec_remote, bash_session, MCP servers, and our own
# re-invocations such as `server` and `model_proxy`). Two things must go:
#
#   1. LD_LIBRARY_PATH — restore it to its pre-bootloader value, otherwise the
#      bundle's lib directory forces foreign children to look for shared
#      libraries inside the bundle before the host distribution, breaking any
#      user binary that depends on system libs newer than the ones we ship.
#
#   2. The PyInstaller `_PYI_*` / `_MEI*` parent-process markers — a child that
#      inherits these treats itself as a *nested* invocation and skips
#      re-establishing LD_LIBRARY_PATH. Combined with (1) that leaves a
#      re-invocation of our own frozen binary (the spawned `server`, or
#      `model_proxy` launched via exec_remote) unable to find bundled libs like
#      libssl. Dropping the markers makes such children bootstrap cleanly as a
#      fresh top-level instance, exactly as a direct invocation does.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    original_ld_library_path = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original_ld_library_path is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original_ld_library_path

    for _key in [k for k in os.environ if k.startswith(("_PYI", "_MEI"))]:
        del os.environ[_key]


@method
async def sandbox_tools_shutdown() -> object:
    """Request graceful shutdown after the JSON-RPC response is sent."""
    # aiohttp starts graceful response draining before this short delay fires,
    # so the caller can receive the shutdown acknowledgement before SIGTERM.
    asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGTERM)
    return Success(None)


async def _cleanup_remote_resources(_app: Application) -> None:
    global _shutdown_complete

    # These modules load remote-tool dependencies such as MCP and Pydantic. The
    # server module is also imported by every short-lived `exec` invocation.
    from inspect_sandbox_tools._remote_tools._bash_session.json_rpc_methods import (
        controller as bash_session_controller,
    )
    from inspect_sandbox_tools._remote_tools._exec_remote.json_rpc_methods import (
        controller as exec_remote_controller,
    )
    from inspect_sandbox_tools._remote_tools._mcp.json_rpc_methods import (
        shutdown as shutdown_mcp_sessions,
    )

    cleanups = (
        ("exec_remote", exec_remote_controller.shutdown),
        ("bash_session", bash_session_controller.shutdown),
        ("mcp", shutdown_mcp_sessions),
    )
    results = await asyncio.gather(
        *(cleanup() for _, cleanup in cleanups), return_exceptions=True
    )
    for (name, _), result in zip(cleanups, results, strict=True):
        if isinstance(result, Exception):
            error = f"{name}: {result}"
            _shutdown_errors.append(error)
            print(f"Failed to clean up {name} resources: {result}", file=sys.stderr)
    _shutdown_complete = True


def _write_shutdown_status() -> None:
    write_private_text(
        _SHUTDOWN_STATUS_TMP_PATH, json.dumps({"errors": _shutdown_errors}) + "\n"
    )
    _SHUTDOWN_STATUS_TMP_PATH.replace(SHUTDOWN_STATUS_PATH)


def _prepare_socket_parent() -> None:
    """Create a verified private parent for only the long-path socket fallback."""
    if SOCKET_PATH.parent == SERVER_DIR:
        return
    # Shared per-user directory: another long-path sample may have created it.
    ensure_private_server_dir(SOCKET_PATH.parent)


def main() -> None:
    global _shutdown_complete

    _shutdown_errors.clear()
    _shutdown_complete = False
    # The server directory is already resolved at import time. Do not expose the
    # internal location to user commands spawned by remote tools.
    os.environ.pop(SERVER_DIR_ENV, None)
    load_tools("inspect_sandbox_tools._remote_tools")

    ensure_private_server_dir(SERVER_DIR)
    _prepare_socket_parent()

    # Remove stale socket file
    SOCKET_PATH.unlink(missing_ok=True)
    SHUTDOWN_STATUS_PATH.unlink(missing_ok=True)
    _SHUTDOWN_STATUS_TMP_PATH.unlink(missing_ok=True)

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)
    app.on_cleanup.append(_cleanup_remote_resources)

    # The only client is the CLI wrapper, which runs as this server's user. The
    # 0700 directory already keeps other users out; a restrictive umask also keeps
    # the socket itself from being connectable should the directory be loosened.
    old_umask = os.umask(0o077)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(SOCKET_PATH))
    except OSError as ex:
        # The filesystem holding the tools tree may not support Unix sockets;
        # a bare errno gives the CLI's "exited immediately" report no context.
        raise RuntimeError(
            f"Cannot bind sandbox-tools server socket {SOCKET_PATH}: "
            f"{ex.strerror or ex}"
        ) from ex
    finally:
        os.umask(old_umask)

    try:
        run_app(app, sock=sock, shutdown_timeout=_HTTP_SHUTDOWN_TIMEOUT)
    finally:
        SOCKET_PATH.unlink(missing_ok=True)
        # Publish completion before removing the PID file so stop-server cannot
        # mistake a clean exit for a crashed daemon in the intervening instant.
        # If publishing itself fails, the PID file must still go, or stop-server
        # waits out its full status timeout; the cleanup errors then survive
        # only in the stderr log (_cleanup_remote_resources printed them).
        try:
            if _shutdown_complete:
                _write_shutdown_status()
        finally:
            _remove_own_pid_file()


def _remove_own_pid_file() -> None:
    """Best-effort removal of a PID file that names this process.

    An unreadable or malformed file is left alone: this runs during shutdown,
    where raising would mask the real exit reason. The CLI, which acts on the
    file's contents, is the place that reports such a file.
    """
    try:
        server_pid = json.loads(read_private_text(SERVER_PID_PATH)).get("pid")
    except (FileNotFoundError, json.JSONDecodeError, RuntimeError, AttributeError):
        server_pid = None
    if server_pid == os.getpid():
        SERVER_PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
