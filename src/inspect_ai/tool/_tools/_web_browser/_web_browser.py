from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool import Tool


def web_browser(*, interactive: bool = True, instance: str | None = None) -> list[Tool]:
    """Removed web browser tools.

    Use `web_search()` for web retrieval, and `computer()` or a browser MCP
    server run via `mcp_server_sandbox()` for web interaction. See
    <https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497>.

    Args:
       interactive: Retained for compatibility with existing calls.
       instance: Retained for compatibility with existing calls.

    Raises:
       PrerequisiteError: Always raised because the web browser tools were removed.
    """
    raise PrerequisiteError(
        "The `web_browser()` tool has been removed. "
        "Use `web_search()` for web retrieval, and `computer()` or a browser MCP "
        "server run via `mcp_server_sandbox()` for web interaction. "
        "See https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497 for migration details."
    )
