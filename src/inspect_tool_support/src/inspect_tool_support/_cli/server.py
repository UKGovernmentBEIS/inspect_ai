import os

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_tool_support._util.constants import SOCKET_PATH
from inspect_tool_support._util.load_tools import load_tools


def main() -> None:
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
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
