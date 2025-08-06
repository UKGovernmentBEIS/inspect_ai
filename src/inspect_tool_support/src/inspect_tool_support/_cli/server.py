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

    # Set umask for world-readable/writable socket (0o666 permissions)
    old_umask = os.umask(0o111)
    try:
        run_app(app, path=str(SOCKET_PATH))
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
