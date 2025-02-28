# TODO:
# This module may be bogus, but I've separated it out from multi_tool_v1.py for now so
# that I don't need to jump through crazy hoops doing a long list of imports two different
# ways - direct execution and package execution.
#
# I'm not sure if this is the best way to do it, but it works for now.
import argparse
import json
import os

from jsonrpcserver import async_dispatch

from multi_tool._constants import SERVER_PORT
from multi_tool._load_tools import load_tools
from multi_tool._util._common_types import JSONRPCResponseJSON
from multi_tool._util._json_rpc_helpers import json_rpc_http_call

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
