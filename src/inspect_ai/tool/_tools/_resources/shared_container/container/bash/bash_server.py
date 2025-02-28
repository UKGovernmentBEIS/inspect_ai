
from aiohttp.web import Application, Request, Response, run_app
from constants import SERVER_PORT
from jsonrpcserver import async_dispatch


def main():
    async def handle_ping(request: Request) -> Response:
        return Response(
            text="Yo\n",
            content_type="text/plain",
        )
    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)
    app.router.add_get("/", handle_ping)

    run_app(app, port=SERVER_PORT)


if __name__ == "__main__":
    main()
