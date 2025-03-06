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
import json

from jsonrpcserver import async_dispatch

from _constants import SERVER_PORT
from _load_tools import load_tools
from _util._common_types import JSONRPCResponseJSON
from _util._json_rpc_helpers import json_rpc_http_call

_SERVER_URL = f"http://localhost:{SERVER_PORT}/"


# Example/testing requests
# {"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}
# {"jsonrpc": "2.0", "method": "bash", "id": 666, "params": {"command": "ls ~/Downloads"}}
async def main() -> None:
    in_process_tools = load_tools("_in_process_tools")
    args: argparse.Namespace = parser.parse_args()
    json_rpc_request_str = args.request
    tool_name = json.loads(json_rpc_request_str)["method"]
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
