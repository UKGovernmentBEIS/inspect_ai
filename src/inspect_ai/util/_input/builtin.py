from ._types import InputRequest, InputResult


async def _dispatch_builtin(request: InputRequest) -> InputResult:
    """Select exactly one built-in handler for ``request``.

    Order: ACP → Textual panel → console. The ACP handler returns
    ``None`` when ``--acp-server`` is not active (no
    :class:`AcpServer` accepting external clients); we then fall
    through to the panel handler, which raises
    :class:`NotImplementedError` when no Textual task display is
    running, in which case we fall through to the console. When
    ``--acp-server`` IS active the ACP handler parks until a client
    attaches and routes exclusively via ACP — see
    ``design/acp/elicitation.md`` "Routing policy".
    """
    from .acp import acp_handler
    from .console import console_handler

    acp_result = await acp_handler(request)
    if acp_result is not None:
        return acp_result

    try:
        from .panel import panel_handler

        return await panel_handler(request)
    except NotImplementedError:
        return await console_handler(request)
