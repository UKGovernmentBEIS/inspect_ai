from __future__ import annotations

import json
import logging
from argparse import Namespace
from textwrap import dedent
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import JsonValue
from shortuuid import uuid

from inspect_ai._util.content import (
    ContentBase,
    ContentText,
)
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import tool_params, validate_tool_input
from inspect_ai.tool import Tool, ToolError, ToolParams
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._span import span

from ..state import HumanAgentState
from .command import HumanAgentCommand

logger = logging.getLogger(__name__)


def _omitted(kind: str) -> str:
    """Terminal marker for non-text content (the full result is in the ToolEvent)."""
    return f"[{kind} content omitted (recorded in transcript)]"


def _validate_cli_flags(tool_def: ToolDef) -> None:
    """Fail closed on parameters whose generated flags collide.

    Argparse raises at parser *construction* on a duplicate option string,
    which bricks the entire generated CLI (including `task submit`), so
    collisions must be rejected host-side before install. Two sources:
    argparse's automatic -h/--help, and the --no-<flag> negative alias that
    BooleanOptionalAction generates for boolean parameters.
    """
    flags: dict[str, str] = {"--help": "argparse help", "-h": "argparse help"}
    for name, schema in tool_def.parameters.properties.items():
        # ToolParams permits arbitrary JSON property names and tool_params()
        # passes them through to **kwargs tools, so models can call such
        # tools — the human CLI must too. Generated literals are emitted via
        # repr() so any name is safe; only the empty name is impossible (it
        # has no flag spelling)
        if not name:
            raise ValueError(
                f"Tool '{tool_def.name}' declares a parameter with an empty "
                "name (no CLI flag can be generated for it)."
            )
        info = _classify_schema(schema.model_dump(exclude_none=True))
        param_flags = [f"--{name.replace('_', '-')}"]
        if info.schema_type == "boolean":
            param_flags.append(f"--no-{name.replace('_', '-')}")
        for flag in param_flags:
            if flag in flags:
                raise ValueError(
                    f"Tool '{tool_def.name}' parameter '{name}' generates "
                    f"CLI flag '{flag}', which collides with {flags[flag]}."
                )
            flags[flag] = f"parameter '{name}'"


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
        # render text parts; note non-text parts rather than discarding the
        # text alongside them (the full result is preserved in the ToolEvent)
        parts: list[str] = []
        for c in result:
            if isinstance(c, ContentText):
                parts.append(c.text)
            else:
                parts.append(_omitted(getattr(c, "type", "non-text")))
        return "\n".join(parts)
    elif isinstance(result, ContentBase):
        # any non-text content (image, audio, video, document, data, ...) —
        # never dump raw payloads (e.g. base64 data URIs) into the terminal
        return _omitted(result.type)
    else:
        return str(result)


class ToolCommand(HumanAgentCommand):
    """Command for calling tools: 'task tool <name> [args]'

    Every parameter is a named argument (task tool addition --x 12 --y 34);
    structured parameters take JSON values (task tool annotate --config '{"a": 1}').
    """

    def __init__(self, tools: list[Tool]):
        self._tools = tools
        self._tool_defs: dict[str, ToolDef] = {}
        self._tool_map: dict[str, Tool] = {}
        for tool in tools:
            tool_def = ToolDef(tool)
            # tool names are interpolated into the generated sandbox script as
            # Python identifiers and string literals — fail closed on names
            # that would break (or inject into) the generated code
            if not tool_def.name.isidentifier():
                raise ValueError(
                    f"Tool name '{tool_def.name}' is not a valid Python "
                    "identifier (required for the generated task CLI)."
                )
            if tool_def.name in self._tool_defs:
                raise ValueError(f"Duplicate tool name '{tool_def.name}'.")
            _validate_cli_flags(tool_def)
            self._tool_defs[tool_def.name] = tool_def
            self._tool_map[tool_def.name] = tool

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

        # JSON value converter for structured parameters (argparse turns
        # ArgumentTypeError into a standard usage error naming the flag)
        lines.append(
            dedent("""
            def _json_arg(value):
                import json
                try:
                    return json.loads(value)
                except json.JSONDecodeError as ex:
                    raise argparse.ArgumentTypeError(f"invalid JSON: {ex}")

            def _nullable(convert):
                # nullable parameters accept the literal 'null' (JSON null)
                def parse(value):
                    return None if value == "null" else convert(value)
                return parse
            """).strip()
        )

        # Create main tool parser with subparsers
        lines.append(
            'tool_parser = subparsers.add_parser("tool", help="Call a tool with arguments.")'
        )
        lines.append('tool_subparsers = tool_parser.add_subparsers(dest="tool_name")')

        # Generate subparser for each tool
        for tool_name, tool_def in self._tool_defs.items():
            parser_code, _ = generate_tool_parser(
                tool_name,
                tool_def.description,
                tool_def.parameters,
            )
            lines.append(parser_code)

        return "\n".join(lines)

    def get_cli_handler_code(self) -> str:
        """Generate CLI handler code for the tool command.

        Returns Python code for the tool() function that:
        - Shows tool list via argparse help if no tool_name
        - Passes tool args to the service as a single dict, out-of-band of
          the routing parameters (so no tool argument name can collide)
        """
        return """
def tool(args):
    tool_name = getattr(args, 'tool_name', None) or ""

    # Handle: task tool (list all tools via argparse help)
    if not tool_name:
        tool_parser.print_help()
        return

    # Tool arguments live under prefixed dests ('arg_<name>'), disjoint from
    # the routing dests ('command', 'tool_name') by construction. Absent
    # optional flags are SUPPRESSed from the namespace, so everything present
    # was explicitly provided — including explicit nulls.
    tool_args = {k[len('arg_'):]: v for k, v in vars(args).items()
                 if k.startswith('arg_')}

    print(call_human_agent("tool", tool=tool_name, arguments=tool_args))
"""

    def cli(self, args: Namespace) -> None:
        # This method is not called - ToolCommand generates its own handler via
        # get_cli_handler_code() which replaces this method in the generated CLI.
        # Method only present to satisfy abstract base class.
        raise Exception("This should never appear in the generated code")

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        # Tool arguments arrive as a single dict, out-of-band of this
        # function's own parameters — no tool argument name can collide
        async def call_tool(tool: str, arguments: dict[str, Any] | None = None) -> str:
            kwargs = arguments or {}

            # Look up tool
            tool_fn = self._tool_map.get(tool)
            if tool_fn is None:
                return f"Error: Unknown tool '{tool}'"

            # model tool calls run inside span(type="tool") — mirror that so
            # nested activity (e.g. model calls made by the tool) attributes
            # to the tool in timelines rather than to the enclosing agent
            async with span(name=tool, type="tool"):
                return await self._execute_tool(tool, tool_fn, kwargs)

        return call_tool

    async def _execute_tool(
        self, tool: str, tool_fn: Tool, kwargs: dict[str, Any]
    ) -> str:
        # Record the event pending, before conversion/execution, with the
        # arguments exactly as sent (they arrived as JSON so they are
        # JSON-safe by construction), then finalize it on every outcome —
        # for human baselines the human's tool usage is the data, so the
        # transcript must carry successes, tool errors, and crashes alike
        event = ToolEvent(
            id=uuid(),
            function=tool,
            arguments=kwargs,
            pending=True,
        )
        transcript()._event(event)

        def finalize(
            result: ToolResult = "",
            error: ToolCallError | None = None,
            failed: bool | None = None,
        ) -> None:
            event._set_result(
                result=result,
                truncated=None,
                error=error,
                waiting_time=0,
                agent=None,
                failed=failed,
                message_id=None,
            )
            # publish the completion — mutation alone leaves the event
            # registered pending (stale live subscribers, pinned forever
            # in bounded transcripts)
            transcript()._event_updated(event)

        # Validate against the declared JSON Schema exactly as the model
        # path does (tool_params() below converts to the Python signature
        # but cannot enforce schema constraints — a ToolDef over **kwargs
        # has no typed signature at all, so this is the only gate that
        # keeps the human's action space identical to the model's)
        validation_errors = validate_tool_input(
            kwargs, self._tool_defs[tool].parameters
        )
        if validation_errors:
            finalize(error=ToolCallError("parsing", validation_errors))
            return f"Error: {validation_errors}"

        # Convert args using tool_params()
        try:
            params = tool_params(kwargs, tool_fn)
        except Exception as e:
            finalize(error=ToolCallError("parsing", str(e)))
            return f"Error parsing tool arguments: {e}"

        try:
            result = await tool_fn(**params)
        except ToolError as ex:
            finalize(error=ToolCallError("unknown", ex.message))
            raise
        except Exception as ex:
            # unexpected exceptions must not end the human's session (a
            # human, unlike a model sample, can read the error and work
            # around a broken tool — and raising here just yields a raw
            # RPC traceback anyway, as the sandbox-service boundary
            # swallows exceptions and keeps polling). Surface a clean
            # message; the failed ToolEvent and this warning keep the
            # breakage visible to analysts and operators.
            logger.warning(f"Error executing human agent tool '{tool}': {ex}")
            finalize(error=ToolCallError("unknown", str(ex)), failed=True)
            return f"Error executing tool '{tool}': {ex}"
        finalize(result=result)

        # Convert result to string
        return tool_result_to_str(result)


class ParamInfo(NamedTuple):
    """Information about a tool parameter for argparse generation."""

    name: str
    schema_type: str | None  # "string", "integer", "number", "boolean", "array", "json"
    is_required: bool
    is_optional: bool  # Has anyOf with null (Optional[T])
    enum: list[Any] | None
    array_item_type: str | None  # For arrays: type of items
    description: str | None
    default: Any


def _complex_info(description: str | None, default: Any) -> ParamInfo:
    """ParamInfo for a structured parameter (takes a JSON value on the CLI)."""
    return ParamInfo(
        name="",
        schema_type="json",
        is_required=False,
        is_optional=False,
        enum=None,
        array_item_type=None,
        description=description,
        default=default,
    )


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
        return _complex_info(schema.get("description"), schema.get("default"))

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
        return _complex_info(description, default)

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
    return _complex_info(description, default)


def _example_instance(schema: dict[str, Any]) -> Any:
    """A minimal example JSON instance for a schema, for help text."""
    if "anyOf" in schema:
        non_null = [x for x in schema["anyOf"] if x.get("type") != "null"]
        return _example_instance(non_null[0]) if non_null else None
    match schema.get("type"):
        case "object":
            properties = schema.get("properties")
            if properties:
                # the example must satisfy the schema it illustrates: every
                # required property, then up to two optional ones for flavor
                required = set(schema.get("required", []))
                keys = [k for k in properties if k in required]
                keys += [k for k in properties if k not in required][:2]
                return {k: _example_instance(properties[k]) for k in keys}
            return {"key": "value"}
        case "array":
            return [_example_instance(schema.get("items", {}))]
        case "string":
            return schema.get("enum", ["text"])[0]
        case "integer":
            return 1
        case "number":
            return 1.5
        case "boolean":
            return True
        case _:
            return "..."


def generate_tool_parser(
    tool_name: str,
    tool_description: str,
    params: ToolParams,
) -> tuple[str, bool]:
    """Generate argparse subparser code for a tool.

    Args:
        tool_name: Name of the tool
        tool_description: Tool description for help text
        params: ToolParams with JSON Schema properties (the source of truth
            for both the argument set and its order)

    Returns:
        Tuple of:
        - parser_code: Python code to add subparser and arguments
        - has_complex_params: True if tool has complex params requiring escape hatch
    """
    lines: list[str] = []
    has_complex_params = False

    # Analyze each parameter (schema order == declaration order)
    param_infos: dict[str, ParamInfo] = {}
    schema_dicts: dict[str, dict[str, Any]] = {}
    for name, schema in params.properties.items():
        # Convert ToolParam to dict for classification
        schema_dict = schema.model_dump(exclude_none=True)
        info = _classify_schema(schema_dict)
        info = info._replace(name=name, is_required=name in params.required)
        param_infos[name] = info
        schema_dicts[name] = schema_dict

        if info.schema_type == "json":
            has_complex_params = True

    # Create subparser (all embedded values emitted via repr() — schema
    # text is data, never code)
    lines.append(
        f"{tool_name}_parser = tool_subparsers.add_parser({tool_name!r}, "
        f"help={tool_description!r}, "
        f"formatter_class=argparse.RawDescriptionHelpFormatter)"
    )

    # Generate arguments in declaration order (all as named args)
    for name, info in param_infos.items():
        arg_name = name.replace("_", "-")
        parts: list[str] = []

        # Always use named args (--x, --y); dests are prefixed so tool
        # argument names can never shadow the parser's routing dests
        # ('command', 'tool_name')
        parts.append(repr(f"--{arg_name}"))
        parts.append(f"dest={f'arg_{name}'!r}")

        # Type conversion; nullable (Optional[T]) scalars accept the literal
        # 'null' so an explicit JSON null is expressible, not just absence
        def converter(base: str, optional: bool = info.is_optional) -> str:
            return f"_nullable({base})" if optional else base

        if info.schema_type == "integer":
            parts.append(f"type={converter('int')}")
        elif info.schema_type == "number":
            parts.append(f"type={converter('float')}")
        elif info.schema_type == "boolean":
            # --flag / --no-flag pair; absent flags are suppressed from the
            # namespace so the tool's own default applies (an absent flag
            # must not silently send False to a tool whose default is True)
            parts.append("action=argparse.BooleanOptionalAction")
        elif info.schema_type == "array":
            parts.append('nargs="*"')
            if info.array_item_type == "integer":
                parts.append("type=int")
            elif info.array_item_type == "number":
                parts.append("type=float")
        elif info.schema_type == "json":
            # structured parameter: the flag's value is JSON ('null' included)
            parts.append("type=_json_arg")
            parts.append('metavar="JSON"')
        elif info.is_optional:
            # nullable string
            parts.append("type=_nullable(str)")

        # Enum/choices (a nullable enum additionally admits None)
        if info.enum:
            choices = [*info.enum, None] if info.is_optional else info.enum
            parts.append(f"choices={choices!r}")
        elif info.schema_type not in ("boolean", "json"):
            # metavar must come from the parameter name — argparse would
            # otherwise derive it from the internal prefixed dest (ARG_X)
            parts.append(f"metavar={name.upper()!r}")

        # Required/default: nullability and requiredness are independent —
        # null is an accepted *value*, it doesn't make the flag omittable.
        # Absent optional flags are suppressed entirely so the handler can
        # distinguish "not provided" from an explicit null
        if info.is_required:
            parts.append("required=True")
        else:
            parts.append("default=argparse.SUPPRESS")

        # Help text (structured params get a copy-pasteable example instance;
        # nullable params advertise the 'null' literal)
        help_text = info.description or ""
        if info.schema_type == "json":
            example = json.dumps(_example_instance(schema_dicts[name]))
            help_text = f"{help_text} (JSON, e.g. '{example}')".strip()
        elif info.is_optional:
            help_text = f"{help_text} ('null' for null)".strip()
        if help_text:
            parts.append(f"help={help_text!r}")

        lines.append(f"{tool_name}_parser.add_argument({', '.join(parts)})")

    parser_code = "\n".join(lines)
    return parser_code, has_complex_params
