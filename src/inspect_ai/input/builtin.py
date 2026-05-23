from ._types import InputRequest, InputResult


async def _dispatch_builtin(request: InputRequest) -> InputResult:
    # Phase 4 will try Textual panel here (NotImplementedError -> fall to console).
    # Phase 6 will try ACP elicitation here (None -> fall to panel/console).
    from .console import console_handler

    return await console_handler(request)
