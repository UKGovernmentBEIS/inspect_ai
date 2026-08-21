from __future__ import annotations

import json
import logging
import math
from argparse import Namespace
from textwrap import dedent
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import JsonValue
from shortuuid import uuid

from inspect_ai._util.content import (
    ContentBase,
    ContentText,
)
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import (
    tool_call_view,
    tool_params,
    validate_tool_input,
)
from inspect_ai.tool import Tool, ToolError, ToolParams
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._anyio import _flatten_exception
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._span import span

from ..._handoff import AgentTool
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
            # handoff() returns an AgentTool, which satisfies list[Tool] but
            # cannot be called directly — the model path special-cases it
            # through agent_handoff(), which has no human equivalent yet
            if isinstance(tool, AgentTool):
                raise ValueError(
                    f"Tool '{registry_unqualified_name(tool)}' is a handoff() "
                    "agent tool, which human_cli(tools=...) does not support."
                )
            tool_def = ToolDef(tool)
            # tool names appear in the generated script only as repr()-quoted
            # literals (generated variables are indexed), so any name inspect
            # accepts works here — e.g. find-item. Only the empty name is
            # impossible (no subcommand spelling)
            if not tool_def.name:
                raise ValueError(
                    "Tool has an empty name (no task tool subcommand can be "
                    "generated for it)."
                )
            if tool_def.name.startswith("-"):
                raise ValueError(
                    f"Tool name '{tool_def.name}' has a leading dash — "
                    "argparse treats it as an option, so no `task tool` "
                    "invocation can reach it on supported Pythons."
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

        # Generate subparser for each tool (variables are indexed, so tool
        # names never appear in generated code outside quoted literals)
        for index, (tool_name, tool_def) in enumerate(self._tool_defs.items()):
            parser_code, _ = generate_tool_parser(
                tool_name,
                tool_def.description,
                tool_def.parameters,
                parser_var=f"parser_{index}",
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
        # apply the tool's custom viewer (if any) so human events render the
        # same way model-invoked events for the same tool do
        call_id = uuid()
        view = tool_call_view(
            ToolCall(id=call_id, function=tool, arguments=kwargs),
            [self._tool_defs[tool]],
        )
        event = ToolEvent(
            id=call_id,
            function=tool,
            arguments=kwargs,
            view=view,
            pending=True,
        )
        transcript()._event(event)

        # snapshot sample waiting time so nested waits (model calls, rate
        # limits) are excluded from the event's working time, as on the
        # model tool path
        waiting_start = sample_waiting_time()

        def finalize(
            result: ToolResult = "",
            error: ToolCallError | None = None,
            failed: bool | None = None,
        ) -> None:
            event._set_result(
                result=result,
                truncated=None,
                error=error,
                waiting_time=sample_waiting_time() - waiting_start,
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
            # an expected tool failure — surface the message the way a model
            # receives it (raising would reach the human as an RPC traceback)
            finalize(error=ToolCallError("unknown", ex.message))
            return f"Error: {ex.message}"
        except LimitExceededError as ex:
            # must reach the sandbox-service boundary, which routes it to
            # sample_active().limit_exceeded() and ends the sample — the
            # generic handler below would silently run past the limit
            finalize(error=ToolCallError("unknown", str(ex)))
            raise
        except Exception as ex:
            # anyio task groups wrap child exceptions in an ExceptionGroup —
            # a contained limit violation must still end the sample, so
            # extract it (nested groups included) and re-raise it
            limit_error = next(
                (
                    e
                    for e in _flatten_exception(ex)
                    if isinstance(e, LimitExceededError)
                ),
                None,
            )
            if limit_error is not None:
                finalize(error=ToolCallError("unknown", str(limit_error)))
                raise limit_error from ex

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
    schema_type: str | None  # "string", "integer", "number", "boolean", "json"
    is_required: bool
    is_optional: bool  # Has anyOf with null (Optional[T])
    enum: list[Any] | None
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
    # Handle anyOf (typically Optional[T]); pydantic places the description
    # and default on the outer anyOf schema, so carry them over when the
    # non-null branch doesn't declare its own
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            info = _classify_schema(non_null[0])
            return info._replace(
                is_optional=True,
                description=info.description or schema.get("description"),
                default=info.default
                if info.default is not None
                else schema.get("default"),
            )
        # Complex union - not simple
        return _complex_info(schema.get("description"), schema.get("default"))

    schema_type = schema.get("type")
    enum = schema.get("enum")
    description = schema.get("description")
    default = schema.get("default")

    # Arrays are structured parameters (JSON values): space-separated
    # tokens cannot express option-looking items like ["-a"] or the empty
    # list, so every array takes a JSON value like other structured types
    if schema_type == "array":
        return _complex_info(description, default)

    # Simple types
    if schema_type in ("string", "integer", "number", "boolean"):
        return ParamInfo(
            name="",
            schema_type=schema_type,
            is_required=False,
            is_optional=False,
            enum=enum,
            description=description,
            default=default,
        )

    # Object or other complex type
    return _complex_info(description, default)


def _example_instance(schema: dict[str, Any]) -> Any:
    """A minimal example JSON instance for a schema, for help text.

    The example must satisfy the schema it illustrates (the service
    validates against it), so authored values take precedence and common
    constraints are honored on generated ones.
    """
    if "anyOf" in schema:
        non_null = [x for x in schema["anyOf"] if x.get("type") != "null"]
        return _example_instance(non_null[0]) if non_null else None
    # prefer authored values — they satisfy the schema by authorship
    if "default" in schema:
        return schema["default"]
    if schema.get("examples"):
        return schema["examples"][0]
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
            if "enum" in schema:
                return schema["enum"][0]
            text = "text"
            min_length = schema.get("minLength")
            if isinstance(min_length, int) and len(text) < min_length:
                text = (text * (min_length // len(text) + 1))[:min_length]
            max_length = schema.get("maxLength")
            if isinstance(max_length, int):
                text = text[:max_length]
            return text
        case "integer":
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)):
                return math.ceil(minimum)
            exclusive = schema.get("exclusiveMinimum")
            if isinstance(exclusive, (int, float)):
                return math.floor(exclusive) + 1
            return 1
        case "number":
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)):
                return float(minimum)
            exclusive = schema.get("exclusiveMinimum")
            if isinstance(exclusive, (int, float)):
                return float(exclusive) + 1.0
            return 1.5
        case "boolean":
            return True
        case _:
            return "..."


def _example_is_valid(instance: Any, schema: dict[str, Any]) -> bool:
    """Whether a generated example actually satisfies its schema.

    Defaults and examples are annotations, not guaranteed-valid instances,
    and the generator can't honor every constraint (pattern, multipleOf,
    ...) — so validate the finished candidate before advertising it.
    """
    try:
        from jsonschema import Draft7Validator

        return Draft7Validator(schema).is_valid(instance)
    except Exception:
        return False


def generate_tool_parser(
    tool_name: str,
    tool_description: str,
    params: ToolParams,
    parser_var: str | None = None,
) -> tuple[str, bool]:
    """Generate argparse subparser code for a tool.

    Args:
        tool_name: Name of the tool
        tool_description: Tool description for help text
        params: ToolParams with JSON Schema properties (the source of truth
            for both the argument set and its order)
        parser_var: Name for the generated parser variable (defaults to
            parser_<tool_name>; callers pass an indexed name so arbitrary
            tool names never form identifiers)

    Returns:
        Tuple of:
        - parser_code: Python code to add subparser and arguments
        - has_complex_params: True if tool has complex params requiring escape hatch
    """
    lines: list[str] = []
    has_complex_params = False
    parser_var = parser_var or f"parser_{tool_name}"

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
    # caller-supplied indexed variable (parser_<i>) so no tool name can
    # shadow routing variables or produce an invalid identifier
    # argparse percent-interpolates help text at render time, so a literal
    # % in a description must be escaped as %% (repr() alone only makes the
    # generated *source* safe)
    lines.append(
        f"{parser_var} = tool_subparsers.add_parser({tool_name!r}, "
        f"help={tool_description.replace('%', '%%')!r}, "
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
        # nullable params advertise the 'null' literal only where it is
        # actually accepted — scalars via _nullable(); arrays reject it
        # during item conversion and booleans have no null spelling)
        help_text = info.description or ""
        if info.schema_type == "json":
            instance = _example_instance(schema_dicts[name])
            example = json.dumps(instance)
            if _example_is_valid(instance, schema_dicts[name]):
                help_text = f"{help_text} (JSON, e.g. '{example}')".strip()
            else:
                help_text = (
                    f"{help_text} (JSON; illustrative shape: '{example}')".strip()
                )
        elif info.is_optional and info.schema_type in ("integer", "number", "string"):
            help_text = f"{help_text} ('null' for null)".strip()
        if help_text:
            # escape argparse's %-interpolation (see add_parser above)
            parts.append(f"help={help_text.replace('%', '%%')!r}")

        lines.append(f"{parser_var}.add_argument({', '.join(parts)})")

    parser_code = "\n".join(lines)
    return parser_code, has_complex_params
