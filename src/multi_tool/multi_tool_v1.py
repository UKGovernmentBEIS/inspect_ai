"""
Command-line interface for multi-tool image.

This script allows the user to execute a specified tool with given parameters.

CLI Parameters:
---------------
request : str
  A JSON string representing the JSON RPC 2.0 request. This should be a valid JSON string that can be parsed into a dictionary.

Usage:
------
python multi_tool_v1.py <request>

Example:
--------
python multi_tool_v1.py '{"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}'
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from typing import Any

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
        from multi_tool._util._common_types import JSONRPCResponseJSON
        from multi_tool._util._json_rpc_helpers import json_rpc_http_call
    except ImportError:
        # If direct imports fail, try adding parent directory to path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from multi_tool._constants import SERVER_PORT
        from multi_tool._load_tools import load_tools
        from multi_tool._util._common_types import JSONRPCResponseJSON
        from multi_tool._util._json_rpc_helpers import json_rpc_http_call
else:
    # Package context (installed via pip)
    module_prefix = __package__
    constants_module = _import_module(f"{module_prefix}._constants")
    load_tools_module = _import_module(f"{module_prefix}._load_tools")
    common_types_module = _import_module(f"{module_prefix}._util._common_types")
    json_rpc_helpers_module = _import_module(f"{module_prefix}._util._json_rpc_helpers")

    SERVER_PORT = constants_module.SERVER_PORT
    load_tools = load_tools_module.load_tools
    JSONRPCResponseJSON = common_types_module.JSONRPCResponseJSON
    json_rpc_http_call = json_rpc_helpers_module.json_rpc_http_call

_SERVER_URL = f"http://localhost:{SERVER_PORT}/"


# Example/testing requests
# {"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}
# {"jsonrpc": "2.0", "method": "bash", "id": 666, "params": {"command": "ls ~/Downloads"}}
async def main() -> None:
    # If installed as a package and running in /opt/inspect, use that as the working directory
    if os.path.exists("/opt/inspect") and __package__ is not None:
        os.chdir("/opt/inspect")

    # Always use the same directory name with leading underscore
    # The _load_tools function will handle the import path differences
    tools_dir = "_in_process_tools"

    in_process_tools = load_tools(tools_dir)
    args: argparse.Namespace = parser.parse_args()
    json_rpc_request_str = args.request
    request_data = json.loads(json_rpc_request_str)
    tool_name = request_data["method"]
    assert isinstance(tool_name, str)

    print(
        await (
            _dispatch_local_method
            if tool_name in in_process_tools
            else _dispatch_remote_method
        )(json_rpc_request_str)
    )


parser = argparse.ArgumentParser(prog="multi_tool_client")
parser.add_argument(
    "request", type=str, help="A JSON string representing the JSON RPC 2.0 request"
)


async def _dispatch_local_method(request_json_str: str) -> JSONRPCResponseJSON:
    return JSONRPCResponseJSON(await async_dispatch(request_json_str))


async def _dispatch_remote_method(request_json_str: str) -> JSONRPCResponseJSON:
    return await json_rpc_http_call(_SERVER_URL, request_json_str)


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(main())
