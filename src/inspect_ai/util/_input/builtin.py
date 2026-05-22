from acp.schema import ElicitationSchema

from ._types import InputResult


async def _dispatch_builtin(message: str, schema: ElicitationSchema) -> InputResult:
    # Phase 4 will try Textual panel here (NotImplementedError -> fall to console).
    # Phase 6 will try ACP elicitation here (None -> fall to panel/console).
    from .console import console_handler

    return await console_handler(message, schema)
