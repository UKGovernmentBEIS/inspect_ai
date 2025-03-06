import os
from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch

# Handle different import contexts
if __package__ is None or __package__ == '':
    # Direct execution
    from _constants import SERVER_PORT
    from _load_tools import load_tools
else:
    # Package context
    from inspect_multi_tool.container._constants import SERVER_PORT
    from inspect_multi_tool.container._load_tools import load_tools


def main() -> None:
    # If installed as a package and running in /opt/inspect, use that as the working directory
    if os.path.exists('/opt/inspect') and __package__ is not None:
        os.chdir('/opt/inspect')
    
    # Use the appropriate tools directory based on the context
    tools_dir = "_remote_tools" if __package__ is None else "remote_tools"
    
    load_tools(tools_dir)

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
