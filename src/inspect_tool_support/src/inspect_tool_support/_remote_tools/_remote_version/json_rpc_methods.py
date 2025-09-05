import os
import sys

from inspect_tool_support._remote_tools._remote_version._playwright_test import (
    exec_playwright_test,
)

from ..._util.json_rpc_helpers import NoParams, validated_json_rpc_method


@validated_json_rpc_method(NoParams)
async def remote_version(_: NoParams) -> str:
    foo = await exec_playwright_test()
    return f"Server: {sys.argv[0]} ({os.getpid()}) {foo}"
