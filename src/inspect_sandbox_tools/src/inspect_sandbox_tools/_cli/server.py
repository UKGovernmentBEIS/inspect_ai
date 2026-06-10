#!/usr/bin/env python3
import os
import socket
import sys

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_sandbox_tools._util.constants import SERVER_DIR, SOCKET_PATH
from inspect_sandbox_tools._util.load_tools import load_tools

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


def main():
    load_tools("inspect_sandbox_tools._remote_tools")

    # Create server directory with permissions based on privilege level.
    # Root: 0o700 prevents the agent from accessing socket/logs.
    # Non-root: 0o777 allows any user (no privilege to escalate anyway).
    SERVER_DIR.mkdir(exist_ok=True)
    os.chmod(SERVER_DIR, 0o700 if os.getuid() == 0 else 0o777)

    # Remove stale socket file
    SOCKET_PATH.unlink(missing_ok=True)

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)

    # When non-root, use permissive umask so any user can connect to the socket.
    # When root, directory permissions (0o700) already block unauthorized access.
    old_umask = os.umask(0o111)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(SOCKET_PATH))
    finally:
        os.umask(old_umask)

    run_app(app, sock=sock)


if __name__ == "__main__":
    main()
