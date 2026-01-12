import json
from argparse import Namespace
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai.model._call_tools import tool_params
from inspect_ai.tool import Tool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_info import ToolInfo, parse_tool_info

from ..._agent import AgentState
from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


def tool_result_to_str(result: ToolResult) -> str:
    """Convert ToolResult to string for CLI display."""
    if isinstance(result, str):
        return result
    elif isinstance(result, (int, float, bool)):
        return str(result)
    elif isinstance(result, ContentText):
        return result.text
    elif isinstance(result, list):
        if len(result) == 0:
            return ""
        if all(isinstance(c, ContentText) for c in result):
            return "\n".join(c.text for c in result)
        raise NotImplementedError("Tool returned non-text content (images/audio/video)")
    elif isinstance(result, (ContentImage, ContentAudio, ContentVideo)):
        raise NotImplementedError("Tool returned non-text content (images/audio/video)")
    else:
        return str(result)


class ToolCommand(HumanAgentCommand):
    """Command for calling tools: 'task tool <name> <json>'"""

    def __init__(self, tools: list[Tool], state: AgentState):
        self._tools = tools
        self._state = state
        self._tool_infos: dict[str, ToolInfo] = {}
        self._tool_map: dict[str, Tool] = {}
        for tool in tools:
            info = parse_tool_info(tool)
            self._tool_infos[info.name] = info
            self._tool_map[info.name] = tool

    @property
    def name(self) -> str:
        return "tool"

    @property
    def description(self) -> str:
        return "Call a tool with JSON arguments."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    @property
    def cli_args(self) -> list[HumanAgentCommand.CLIArg]:
        return [
            HumanAgentCommand.CLIArg(
                name="tool_name",
                description="Name of tool to call",
            ),
            HumanAgentCommand.CLIArg(
                name="json_args",
                description="JSON object with tool arguments",
            ),
        ]

    def cli(self, args: Namespace) -> None:
        # Pass through to service - it handles help/list/execute based on args
        tool_name = args.tool_name or ""
        json_args = args.json_args or ""
        print(call_human_agent("tool", name=tool_name, json_args=json_args))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def call_tool(name: str, json_args: str) -> str:
            # Handle: task tool (no args) - list tools
            if not name:
                return self._format_tool_list()

            # Handle: task tool <name> --help or task tool <name> (no json)
            if not json_args or json_args == "--help":
                return self._format_tool_help(name)

            # Look up tool
            tool = self._tool_map.get(name)
            if tool is None:
                return f"Error: Unknown tool '{name}'"

            # Parse JSON
            try:
                args = json.loads(json_args)
            except json.JSONDecodeError as e:
                return f"Error: Invalid JSON: {e}"

            # Convert args using tool_params()
            try:
                params = tool_params(args, tool)
            except Exception as e:
                return f"Error parsing tool arguments: {e}"

            # Call tool (let exceptions propagate naturally for ToolError etc.)
            result = await tool(**params)

            # Convert result to string
            return tool_result_to_str(result)

        return call_tool

    def _format_tool_list(self) -> str:
        """Format available tools with descriptions."""
        lines = ["Available tools:", ""]
        for name, info in self._tool_infos.items():
            lines.append(f"  {name}: {info.description}")
        lines.append("")
        lines.append("Use 'task tool <name> --help' for details on a specific tool.")
        return "\n".join(lines)

    def _format_tool_help(self, name: str) -> str:
        """Format description + full JSON schema for a tool."""
        info = self._tool_infos.get(name)
        if info is None:
            lines = [f"Error: Unknown tool '{name}'", "", "Available tools:"]
            for tool_name in self._tool_infos:
                lines.append(f"  {tool_name}")
            return "\n".join(lines)

        lines = [
            f"{info.name}: {info.description}",
            "",
            "Parameters:",
            json.dumps(info.parameters.model_dump(exclude_none=True), indent=2),
        ]
        return "\n".join(lines)
