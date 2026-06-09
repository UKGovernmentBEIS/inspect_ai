from inspect_ai.tool import Tool, ToolDef, ToolResult, tool
from collections.abc import Sequence

def _tool_defs(tools: Sequence[Tool] | None) -> list[ToolDef]:
    """Convert allowed tools into ToolDef objects."""
    return [ToolDef(tool) for tool in tools or []]

def _tool_signature(tool_def: ToolDef) -> str:
    """Return a compact signature for an allowlisted tool."""
    parameters = tool_def.parameters
    if parameters is None or parameters.properties is None:
        return f"{tool_def.name}()"

    args: list[str] = []
    required = set(parameters.required or [])

    for name, schema in parameters.properties.items():
        typ = schema.type or "any"
        optional = "" if name in required else " | None"
        args.append(f"{name}: {typ}{optional}")

    return f"{tool_def.name}({', '.join(args)})"


def _tool_interface_description(tool_defs: list[ToolDef]) -> str:
    """Describe the tools that will eventually be callable from run_code."""
    if not tool_defs:
        return (
            "No inner tools are currently available. "
            "The code can only use the Python execution environment."
        )

    lines = [
        "The code may eventually call the following allowlisted Inspect tools:",
        "",
    ]

    for tool_def in tool_defs:
        lines.append(
            f"- `{_tool_signature(tool_def)}`: {tool_def.description}"
        )

    return "\n".join(lines)

@tool
def run_code(
    tools: Sequence[Tool] | None = None,
    timeout: int | None = None,
) -> Tool:
    """Run Python code that can orchestrate selected tools.

    Args:
        tools: Tools that code executed by run_code may eventually call.
        timeout: Maximum execution time in seconds.
    """

    tool_defs = _tool_defs(tools)
    inner_tools_description = _tool_interface_description(tool_defs)

    async def execute(code: str) -> str:
        """Run Python code.

        Args:
            code: Python code to execute.
        """
        return "run_code execution is not implemented yet"

    return ToolDef(
        execute,
        name="run_code",
        description=(
            "Run Python code that can orchestrate selected tools.\n\n"
            f"{inner_tools_description}\n\n"
            "This placeholder does not execute code yet."
        ),
    ).as_tool()
