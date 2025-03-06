import importlib
import os
import sys
from typing import Any

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import async_dispatch


# Use dynamic imports to handle both development and installation contexts
def _import_module(module_path: str) -> Any:
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        print(f"Error importing {module_path}: {e}")
        raise


# Handle imports based on execution context
if __package__ is None or __package__ == "":
    # Direct execution during development
    try:
        from multi_tool._constants import SERVER_PORT
        from multi_tool._load_tools import load_tools
    except ImportError:
        # If direct imports fail, try adding parent directory to path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from multi_tool._constants import SERVER_PORT
        from multi_tool._load_tools import load_tools
else:
    # Package context (installed via pip)
    module_prefix = __package__
    constants_module = _import_module(f"{module_prefix}._constants")
    load_tools_module = _import_module(f"{module_prefix}._load_tools")

    SERVER_PORT = constants_module.SERVER_PORT
    load_tools = load_tools_module.load_tools


def main() -> None:
    # If installed as a package and running in /opt/inspect, use that as the working directory
    if os.path.exists("/opt/inspect") and __package__ is not None:
        os.chdir("/opt/inspect")

    # Always use the same directory name with leading underscore
    # The _load_tools function will handle the import path differences
    tools_dir = "_remote_tools"

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
if __name__ == "__main__":
    main()
