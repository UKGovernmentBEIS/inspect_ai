from __future__ import annotations

import inspect
import json
from argparse import Namespace
from typing import Awaitable, Callable, Literal, NamedTuple, Any

from pydantic import JsonValue

from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai.model._call_tools import tool_params
from inspect_ai.tool import Tool, ToolParams
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_def import ToolDef

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
        texts: list[str] = []
        for c in result:
            if isinstance(c, ContentText):
                texts.append(c.text)
            else:
                raise NotImplementedError(
                    "Tool returned non-text content (images/audio/video)"
                )
        return "\n".join(texts)
    elif isinstance(result, (ContentImage, ContentAudio, ContentVideo)):
        raise NotImplementedError("Tool returned non-text content (images/audio/video)")
    else:
        return str(result)


class ToolCommand(HumanAgentCommand):
    """Command for calling tools: 'task tool <name> [args]'

    Supports three argument styles:
    - Positional: task tool addition 12 34
    - Named: task tool addition --x 12 --y 34
    - JSON escape hatch: task tool addition --raw-json-escape-hatch '{"x": 12}'
    """

    def __init__(self, tools: list[Tool], state: AgentState):
        self._tools = tools
        self._state = state
        self._tool_defs: dict[str, ToolDef] = {}
        self._tool_map: dict[str, Tool] = {}
        self._tool_param_order: dict[str, list[str]] = {}
        for tool in tools:
            tool_def = ToolDef(tool)
            self._tool_defs[tool_def.name] = tool_def
            self._tool_map[tool_def.name] = tool
            self._tool_param_order[tool_def.name] = get_param_order_from_tool(tool)

    @property
    def name(self) -> str:
        return "tool"

    @property
    def description(self) -> str:
        return "Call a tool with arguments."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 2

    @property
    def cli_args(self) -> list[HumanAgentCommand.CLIArg]:
        # No static args - we use dynamic per-tool subparsers
        return []

    def get_cli_parser_code(self) -> str:
        """Generate argparse subparser code for all tools.

        Returns Python code that creates nested subparsers:
        - tool_parser: main 'task tool' parser
        - tool_subparsers: subparser for each tool (e.g., 'task tool addition')
        """
        lines: list[str] = []

        # Create main tool parser with subparsers
        lines.append(
            'tool_parser = subparsers.add_parser("tool", help="Call a tool with arguments.")'
        )
        lines.append('tool_subparsers = tool_parser.add_subparsers(dest="tool_name")')

        # Generate subparser for each tool
        tool_param_names: dict[str, list[str]] = {}
        for tool_name, tool_def in self._tool_defs.items():
            param_order = self._tool_param_order[tool_name]
            parser_code, param_names = generate_tool_parser(
                tool_name,
                tool_def.description,
                tool_def.parameters,
                param_order,
            )
            lines.append(parser_code)
            tool_param_names[tool_name] = param_names

        # Generate TOOL_PARAMS metadata dict
        lines.append("")
        lines.append("# Tool parameter metadata for arg conversion")
        lines.append(f"TOOL_PARAMS = {tool_param_names!r}")

        return "\n".join(lines)

    def get_cli_handler_code(self) -> str:
        """Generate CLI handler code for the tool command.

        Returns Python code for the tool() function that:
        - Pre-parses for --raw-json-escape-hatch to bypass argparse validation
        - Lists tools if no tool_name
        - Converts args to JSON and calls the service
        """
        return f"""
{ARGS_TO_JSON_CODE}

def tool(args):
    tool_name = getattr(args, 'tool_name', None) or ""

    # Handle: task tool (list all tools)
    if not tool_name:
        print(call_human_agent("tool", name="", json_args=""))
        return

    # Get parameter names for this tool
    param_names = TOOL_PARAMS.get(tool_name, [])

    # Build JSON from positional/named args
    json_args = args_to_json(vars(args), param_names)

    print(call_human_agent("tool", name=tool_name, json_args=json_args))
"""

    def cli(self, args: Namespace) -> None:
        # This method is not called - ToolCommand generates its own handler via
        # get_cli_handler_code() which replaces this method in the generated CLI.
        # Method only present to satisfy abstract base class.
        raise Exception("This should never appear in the generated code")

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
        for name, tool_def in self._tool_defs.items():
            lines.append(f"  {name}: {tool_def.description}")
        lines.append("")
        lines.append("Use 'task tool <name> --help' for details on a specific tool.")
        return "\n".join(lines)

    def _format_tool_help(self, name: str) -> str:
        """Format description + full JSON schema for a tool."""
        tool_def = self._tool_defs.get(name)
        if tool_def is None:
            lines = [f"Error: Unknown tool '{name}'", "", "Available tools:"]
            for tool_name in self._tool_defs:
                lines.append(f"  {tool_name}")
            return "\n".join(lines)

        lines = [
            f"{tool_def.name}: {tool_def.description}",
            "",
            "Parameters:",
            json.dumps(tool_def.parameters.model_dump(exclude_none=True), indent=2),
        ]
        return "\n".join(lines)


class ParamInfo(NamedTuple):
    """Information about a tool parameter for argparse generation."""

    name: str
    schema_type: str | None  # "string", "integer", "number", "boolean", "array", None
    is_required: bool
    is_optional: bool  # Has anyOf with null (Optional[T])
    enum: list[Any] | None
    array_item_type: str | None  # For arrays: type of items
    description: str | None
    default: Any


def _classify_schema(schema: dict[str, Any]) -> ParamInfo:
    """Classify a JSON schema property for argparse mapping.

    Args:
        schema: JSON Schema dict for a single parameter

    Returns:
        ParamInfo with extracted type information
    """
    # Handle anyOf (typically Optional[T])
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            info = _classify_schema(non_null[0])
            return info._replace(is_optional=True)
        # Complex union - not simple
        return ParamInfo(
            name="",
            schema_type=None,
            is_required=False,
            is_optional=False,
            enum=None,
            array_item_type=None,
            description=schema.get("description"),
            default=schema.get("default"),
        )

    schema_type = schema.get("type")
    enum = schema.get("enum")
    description = schema.get("description")
    default = schema.get("default")

    # Handle arrays
    if schema_type == "array":
        items = schema.get("items", {})
        items_type = items.get("type")
        if items_type in ("string", "integer", "number"):
            return ParamInfo(
                name="",
                schema_type="array",
                is_required=False,
                is_optional=False,
                enum=None,
                array_item_type=items_type,
                description=description,
                default=default,
            )
        # Complex array items - not simple
        return ParamInfo(
            name="",
            schema_type=None,
            is_required=False,
            is_optional=False,
            enum=None,
            array_item_type=None,
            description=description,
            default=default,
        )

    # Simple types
    if schema_type in ("string", "integer", "number", "boolean"):
        return ParamInfo(
            name="",
            schema_type=schema_type,
            is_required=False,
            is_optional=False,
            enum=enum,
            array_item_type=None,
            description=description,
            default=default,
        )

    # Object or other complex type
    return ParamInfo(
        name="",
        schema_type=None,
        is_required=False,
        is_optional=False,
        enum=None,
        array_item_type=None,
        description=description,
        default=default,
    )


def _is_simple_type(info: ParamInfo) -> bool:
    """Check if parameter info represents an argparse-compatible type."""
    return info.schema_type in ("string", "integer", "number", "boolean", "array")


def _escape_string(s: str) -> str:
    """Escape a string for embedding in generated Python code."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def generate_tool_parser(
    tool_name: str,
    tool_description: str,
    params: ToolParams,
    param_order: list[str],
) -> tuple[str, list[str]]:
    """Generate argparse subparser code for a tool.

    Args:
        tool_name: Name of the tool
        tool_description: Tool description for help text
        params: ToolParams with JSON Schema properties
        param_order: Parameter names in signature order (for positional args)

    Returns:
        Tuple of:
        - parser_code: Python code to add subparser and arguments
        - param_names: List of parameter names for handler metadata
    """
    lines: list[str] = []
    positional_params: list[str] = []
    named_params: list[str] = []
    has_complex_params = False

    # Analyze each parameter
    param_infos: dict[str, ParamInfo] = {}
    for name in param_order:
        if name not in params.properties:
            continue

        schema = params.properties[name]
        # Convert ToolParam to dict for classification
        schema_dict = schema.model_dump(exclude_none=True)
        info = _classify_schema(schema_dict)
        info = info._replace(name=name, is_required=name in params.required)
        param_infos[name] = info

        if not _is_simple_type(info):
            has_complex_params = True

    # Create subparser
    escaped_desc = _escape_string(tool_description)
    lines.append(
        f'{tool_name}_parser = tool_subparsers.add_parser("{tool_name}", '
        f'help="{escaped_desc}")'
    )

    # Generate arguments in signature order
    for name in param_order:
        if name not in param_infos:
            continue

        info = param_infos[name]

        if not _is_simple_type(info):
            # Complex type - skip, user must use --raw-json-escape-hatch
            continue

        arg_name = name.replace("_", "-")
        parts: list[str] = []

        # Determine if positional or named
        # Positional: required, simple type, not boolean, not array
        use_positional = (
            info.is_required
            and not info.is_optional
            and info.schema_type not in ("boolean", "array")
        )

        if use_positional:
            positional_params.append(name)
            parts.append(f'"{name}"')  # Positional arg (no --)
        else:
            named_params.append(name)
            parts.append(f'"--{arg_name}"')
            parts.append(f'dest="{name}"')

        # Type conversion
        if info.schema_type == "integer":
            parts.append("type=int")
        elif info.schema_type == "number":
            parts.append("type=float")
        elif info.schema_type == "boolean":
            parts.append('action="store_true"')
            parts.append("default=False")
        elif info.schema_type == "array":
            parts.append('nargs="*"')
            if info.array_item_type == "integer":
                parts.append("type=int")
            elif info.array_item_type == "number":
                parts.append("type=float")

        # Enum/choices
        if info.enum:
            parts.append(f"choices={info.enum!r}")

        # Required/default for named args
        if not use_positional and info.schema_type != "boolean":
            if info.is_optional or not info.is_required:
                parts.append("default=None")
            else:
                parts.append("required=True")

        # Help text
        if info.description:
            escaped = _escape_string(info.description)
            parts.append(f'help="{escaped}"')

        lines.append(f'{tool_name}_parser.add_argument({", ".join(parts)})')

    # If tool has complex params, add a note in help
    if has_complex_params:
        lines.append(
            f"{tool_name}_parser.epilog = "
            f'"Note: This tool has complex parameters. Use --raw-json-escape-hatch."'
        )

    parser_code = "\n".join(lines)
    all_param_names = positional_params + named_params

    return parser_code, all_param_names


def get_param_order_from_tool(tool: Callable[..., Any]) -> list[str]:
    """Extract parameter names in order from a tool's signature.

    Args:
        tool: The tool callable

    Returns:
        List of parameter names in signature order
    """
    sig = inspect.signature(tool)
    return list(sig.parameters.keys())


ARGS_TO_JSON_CODE = '''
def args_to_json(args_dict, param_names):
    """Convert argparse namespace to JSON string."""
    import json
    result = {}
    for name in param_names:
        # Handle both underscore and hyphen variants
        key = name.replace("-", "_")
        value = args_dict.get(key)
        if value is not None:
            result[name] = value
    return json.dumps(result) if result else "{}"
'''
