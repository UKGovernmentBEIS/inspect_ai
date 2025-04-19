from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

from inspect_tool_support._util.constants import SERVER_PORT
from inspect_tool_support._util.load_tools import load_tools


def main() -> None:
    load_tools("inspect_tool_support._remote_tools")

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)

    print(f"Starting server on port {SERVER_PORT}")
    run_app(app, port=SERVER_PORT)


if __name__ == "__main__":
    main()
