import os
import sys

from ..._util.json_rpc_helpers import NoParams, validated_json_rpc_method


@validated_json_rpc_method(NoParams)
async def version(_: NoParams) -> str:
    return f"Client: {sys.argv[0]} ({os.getpid()})"
