#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch
from playwright.async_api import async_playwright

from inspect_tool_support._util.constants import SOCKET_PATH
from inspect_tool_support._util.load_tools import load_tools

print(f"\n\nXXXXX server.py module loaded ({os.getpid()})")

# When running as a PyInstaller onefile binary, all bundled shared libs are extracted
# under sys._MEIPASS. Ensure the dynamic linker can find them by prepending that
# lib directory to LD_LIBRARY_PATH before launching Chromium.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    meipass_lib = Path(sys._MEIPASS) / "lib"
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
    os.environ["LD_LIBRARY_PATH"] = new_ld
    print(f"LD_LIBRARY_PATH set to {os.environ['LD_LIBRARY_PATH']}")
    # Hint Playwright to use packaged browsers and skip host validation inside minimal containers
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    # os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")
    os.environ["DEBUG"] = (
        "pw:api,pw:browser,pw:channel,pw:driver,pw:page,pw:network,pw:proxy,pw:fetch"
    )


def main():
    load_tools("inspect_tool_support._remote_tools")

    # Remove stale socket file
    SOCKET_PATH.unlink(missing_ok=True)

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)

    print(f"Starting server on Unix socket: {SOCKET_PATH}")
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
        run_app(app, path=str(SOCKET_PATH))
    except Exception as ex:
        print(f"Server caught {ex}")
        raise
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
