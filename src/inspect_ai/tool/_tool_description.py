from dataclasses import dataclass

from ._tool import Tool
from ._tool_params import ToolParams


@dataclass
class ToolDescription:
    name: str | None = None
    description: str | None = None
    parameters: ToolParams | None = None


def tool_description(tool: Tool) -> ToolDescription:
    return getattr(tool, TOOL_DESCRIPTION, ToolDescription())


def set_tool_description(tool: Tool, description: ToolDescription) -> None:
    setattr(tool, TOOL_DESCRIPTION, description)


TOOL_DESCRIPTION = "__TOOL_DESCRIPTION__"
