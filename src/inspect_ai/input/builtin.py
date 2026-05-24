from ._types import InputRequest, InputResult


async def _dispatch_builtin(request: InputRequest) -> InputResult:
    # Phase 6 will try ACP elicitation here (None -> fall to panel/console).
    from .console import console_handler

    try:
        from .panel import panel_handler

        return await panel_handler(request)
    except NotImplementedError:
        return await console_handler(request)
