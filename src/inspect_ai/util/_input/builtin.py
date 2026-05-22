from acp.schema import ElicitationSchema

from ._types import InputResult


async def _dispatch_builtin(message: str, schema: ElicitationSchema) -> InputResult:
    raise NotImplementedError(
        "No built-in input handler available "
        "(console/panel/ACP handlers land in later phases)."
    )
