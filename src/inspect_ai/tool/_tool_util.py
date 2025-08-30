from ._tool import Tool
from ._tool_def import ToolDef
from ._tool_info import ToolInfo


def tool_to_tool_info(tool: Tool) -> ToolInfo:
    tool_def = ToolDef(tool)
    return ToolInfo(
        name=tool_def.name,
        description=tool_def.description,
        parameters=tool_def.parameters,
        options=tool_def.options,
    )
