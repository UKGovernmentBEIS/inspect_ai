#!/usr/bin/env python3
import os
import socket
import sys
from pathlib import Path

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_sandbox_tools._util.constants import SOCKET_PATH
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

    # Remove stale socket file
    SOCKET_PATH.unlink(missing_ok=True)

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)

    # Set umask to handle dynamic user switching scenarios:
    # The server is created on-demand by the first client call, but subsequent
    # calls may come from different users. We must support all combinations:
    # - root creates socket, non-root clients connect later
    # - non-root creates socket, root connects later
    # - non-root1 creates socket, non-root2 connects later
    # Using umask 0o111 creates socket with 0o666 permissions (rw-rw-rw-)
    # allowing any user to connect regardless of who created the socket
    old_umask = os.umask(0o111)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(SOCKET_PATH))
    finally:
        os.umask(old_umask)

    run_app(app, sock=sock)


if __name__ == "__main__":
    main()
