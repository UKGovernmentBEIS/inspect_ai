from openai.types.responses import (
    WebSearchToolParam,
)

from inspect_ai.tool._tool_info import ToolInfo


def maybe_web_search_tool(tool: ToolInfo) -> WebSearchToolParam | None:
    return (
        # TODO: Pull the options out of tool.options as well
        WebSearchToolParam(type="web_search_preview", search_context_size="high")
        if tool.options and tool.options.get("use_internal", False)
        else None
    )
