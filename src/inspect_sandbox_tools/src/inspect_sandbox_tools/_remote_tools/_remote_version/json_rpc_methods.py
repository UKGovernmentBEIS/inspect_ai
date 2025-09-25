import os
import sys

from ..._util.json_rpc_helpers import NoParams, validated_json_rpc_method


@validated_json_rpc_method(NoParams)
async def remote_version(_: NoParams) -> str:
    return f"Server: {sys.argv[0]} ({os.getpid()})"
