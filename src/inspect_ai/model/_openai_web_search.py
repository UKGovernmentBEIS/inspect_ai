from openai.types.responses import (
    WebSearchToolParam,
)

from inspect_ai.tool._tool_info import ToolInfo


def maybe_web_search_tool(tool: ToolInfo) -> WebSearchToolParam | None:
    return (
        WebSearchToolParam(type="web_search_preview", search_context_size="high")
        if tool.options and tool.options.get("provider", None) == "internal"
        else None
    )
