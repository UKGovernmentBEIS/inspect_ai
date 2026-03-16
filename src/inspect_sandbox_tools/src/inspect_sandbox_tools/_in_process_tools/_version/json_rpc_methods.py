from inspect_sandbox_tools import __version__

from ..._util.json_rpc_helpers import NoParams, validated_json_rpc_method


@validated_json_rpc_method(NoParams)
async def version(_: NoParams) -> str:
    return __version__
