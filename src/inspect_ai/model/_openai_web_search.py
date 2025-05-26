from typing import cast

from openai.types.responses import WebSearchTool, WebSearchToolParam

from inspect_ai.tool._tool_info import ToolInfo


def maybe_web_search_tool(tool: ToolInfo) -> WebSearchToolParam | None:
    return (
        _web_search_tool(tool.options["openai"])
        if tool.name == "web_search" and tool.options and "openai" in tool.options
        else None
    )


def _web_search_tool(maybe_openai_options: object) -> WebSearchToolParam:
    if maybe_openai_options is None:
        maybe_openai_options = {}
    elif not isinstance(maybe_openai_options, dict):
        raise TypeError(
            f"Expected a dictionary for openai_options, got {type(maybe_openai_options)}"
        )
    openai_options = (
        WebSearchTool.model_validate(
            {"type": "web_search_preview", **maybe_openai_options}
        )
        if maybe_openai_options
        else WebSearchTool(type="web_search_preview")
    )

    return cast(WebSearchToolParam, openai_options.model_dump(exclude_none=True))
