from inspect_tool_support import __version__

from ..._util.json_rpc_helpers import NoParams, validated_json_rpc_method
from ..._util.semver import pep440_to_semver


@validated_json_rpc_method(NoParams)
async def version(_: NoParams) -> str:
    return str(pep440_to_semver(__version__))
