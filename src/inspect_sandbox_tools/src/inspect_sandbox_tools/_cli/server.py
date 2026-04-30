#!/usr/bin/env python3
import os
import socket
import sys

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_sandbox_tools._util.constants import SERVER_DIR, SOCKET_PATH
from inspect_sandbox_tools._util.load_tools import load_tools

# When running as a PyInstaller onefile binary, the bootloader prepends the
# bundle's extracted lib directory to LD_LIBRARY_PATH so the daemon's native
# dependencies can be loaded, and saves the user's original value to
# LD_LIBRARY_PATH_ORIG. By the time this module is imported every C extension
# the daemon needs has already been resolved, so we restore LD_LIBRARY_PATH to
# its pre-bootloader value. Otherwise the bundle's lib directory propagates
# via os.environ into every subprocess we spawn (exec_remote, bash_session,
# MCP servers) and forces those children to look for shared libraries inside
# the bundle before the host distribution — breaking any user binary that
# depends on system libs newer than the ones the bundle ships.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    original_ld_library_path = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original_ld_library_path is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original_ld_library_path


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
