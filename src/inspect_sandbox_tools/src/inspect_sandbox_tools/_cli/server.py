#!/usr/bin/env python3
import os
import socket
import sys
from pathlib import Path

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_sandbox_tools._util.constants import SERVER_DIR, SOCKET_PATH
from inspect_sandbox_tools._util.load_tools import load_tools

# When running as a PyInstaller onefile binary, all bundled shared libs are extracted
# under sys._MEIPASS. Ensure the dynamic linker can find them by prepending that
# lib directory to LD_LIBRARY_PATH before launching Chromium.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    meipass_lib = Path(sys._MEIPASS) / "lib"
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
    os.environ["LD_LIBRARY_PATH"] = new_ld


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
