from __future__ import annotations

import contextlib
import json
import math
from argparse import Namespace
from textwrap import dedent
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, NamedTuple

import anyio
from pydantic import JsonValue
from shortuuid import uuid

from inspect_ai._util.content import (
    ContentBase,
    ContentText,
)
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai._util.working import sample_clock, sample_working_time_since
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import (
    ClassifiedToolException,
    classify_tool_exception,
    resolve_tool_content,
    tool_call_view,
    tool_params,
    truncate_tool_output,
    validate_tool_input,
)
from inspect_ai.model._generate_config import active_generate_config
from inspect_ai.tool import Tool, ToolParams
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from inspect_ai.util._sandbox.service import find_control_flow
from inspect_ai.util._span import span

from ..._handoff import AgentTool
from ..state import HumanAgentState
from .command import HumanAgentCommand


class _ToolScheduler:
    """Concurrency semantics matching the model path's execution stages.

    SandboxService handles pending request files concurrently, so two shell
    invocations can arrive at once. As on the model path (where each serial
    call is its own single-element stage — see _call_tools.py), a tool
    declaring parallel=False is a global barrier: it runs concurrently with
    nothing, not even a different tool. parallel=True tools run freely
    alongside each other.
    """

    def __init__(self) -> None:
        self._condition = anyio.Condition()
        self._parallel_active = 0
        self._serial_active = False

    @contextlib.asynccontextmanager
    async def slot(self, parallel: bool) -> AsyncIterator[None]:
        if parallel:
            async with self._condition:
                while self._serial_active:
                    await self._condition.wait()
                self._parallel_active += 1
            try:
                yield
            finally:
                # shielded: a cancelled call must still release its slot
                with anyio.CancelScope(shield=True):
                    async with self._condition:
                        self._parallel_active -= 1
                        self._condition.notify_all()
        else:
            async with self._condition:
                while self._serial_active or self._parallel_active > 0:
                    await self._condition.wait()
                self._serial_active = True
            try:
                yield
            finally:
                with anyio.CancelScope(shield=True):
                    async with self._condition:
                        self._serial_active = False
                        self._condition.notify_all()


# JSON value converter for structured parameters (argparse turns
# ArgumentTypeError into a standard usage error naming the flag)
_JSON_ARG_CODE = dedent("""
    def _json_arg(value):
        import json
        try:
            return json.loads(value)
        except json.JSONDecodeError as ex:
            raise argparse.ArgumentTypeError(f"invalid JSON: {ex}")
    """).strip()


def _help(text: str) -> str:
    """Escape help text for argparse, which %-interpolates it at render time.

    repr() makes generated *source* safe; this makes the rendered help safe
    for any tool description or property name.
    """
    return text.replace("%", "%%")


def _omitted(kind: str) -> str:
    """Terminal marker for non-text content (the full result is in the ToolEvent)."""
    return f"[{kind} content omitted (recorded in transcript)]"


def _validate_cli_flags(tool_def: ToolDef) -> None:
    """Fail closed on parameters whose generated flags collide.

    Argparse raises at parser *construction* on a duplicate option string,
    which bricks the entire generated CLI (including `task submit`), so
    collisions must be rejected host-side before install. Sources:
    argparse's automatic -h/--help, the --no-<flag> false flag generated
    for boolean parameters, and the --null-<flag> flag generated for
    nullable parameters.
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
        if info.is_optional:
            param_flags.append(f"--null-{name.replace('_', '-')}")
        for flag in param_flags:
            if flag in flags:
                raise ValueError(
                    f"Tool '{tool_def.name}' parameter '{name}' generates "
                    f"CLI flag '{flag}', which collides with {flags[flag]}."
                )
            flags[flag] = f"parameter '{name}'"


def _validate_parser_builds(tool_def: ToolDef) -> None:
    """Fail closed if the tool's generated parser cannot be built or render help.

    Builds the generated subparser host-side and renders its help, so
    anything argparse rejects when the sandbox CLI loads (which breaks every
    `task` command) or when `task tool <name> --help` runs is caught before
    install.
    """
    import argparse

    parser_code, _ = generate_tool_parser(
        tool_def.name, tool_def.description, tool_def.parameters, "parser_0"
    )
    tool_subparsers = argparse.ArgumentParser().add_subparsers()
    namespace: dict[str, Any] = {
        "argparse": argparse,
        "tool_subparsers": tool_subparsers,
    }
    try:
        exec(
            compile(f"{_JSON_ARG_CODE}\n{parser_code}", "<generated>", "exec"),
            namespace,
        )
        namespace["parser_0"].format_help()
    except Exception as ex:
        raise ValueError(
            f"Tool '{tool_def.name}' cannot be offered via `task tool`: "
            f"its generated command-line parser fails to build ({ex})."
        ) from ex


def _raise_if_control_flow(ex: Exception, finalize: Callable[..., None]) -> None:
    """Finalize the event and re-raise `ex` if it carries a sample termination.

    The sandbox service treats termination as sticky across the whole causal
    history (group leaves, causes, context) and enacts it when the exception
    reaches the dispatcher, so this must run before an exception is reduced
    to a classification or a reply.
    """
    control = find_control_flow(ex)
    if control is not None:
        finalize(error=ToolCallError("unknown", str(control)))
        raise ex


def _capped(tool: str, reply: str, max_output: int | None) -> str:
    """Bound a terminal reply by the tool's output limit (shared truncation)."""
    truncated = truncate_tool_output(tool, reply, max_output)
    return truncated.output if truncated else reply


def _group_leaves(ex: Exception) -> list[Exception]:
    """The leaves of an exception group in group order (`[ex]` otherwise)."""
    if isinstance(ex, ExceptionGroup):
        return [leaf for child in ex.exceptions for leaf in _group_leaves(child)]
    return [ex]


class _DecisiveException(NamedTuple):
    exception: Exception
    classified: ClassifiedToolException | None
    """None when the exception is unexpected."""


def _decisive_exception(ex: Exception, tool: str) -> _DecisiveException:
    """The exception that decides a tool failure's disposition, classified.

    inner_exception() reduces a group to one leaf in no particular order,
    which can hide an unexpected exception or a limit behind an expected
    error. Every leaf is classified instead: the first unexpected leaf wins,
    then the first limit; otherwise the first leaf (all are expected errors).
    """
    leaves = [
        _DecisiveException(leaf, classify_tool_exception(leaf, tool))
        for leaf in _group_leaves(ex)
    ]
    for leaf in leaves:
        if leaf.classified is None:
            return leaf
    for leaf in leaves:
        if isinstance(leaf.exception, LimitExceededError) and not isinstance(
            leaf.exception, OutputLimitExceededError
        ):
            return leaf
    return leaves[0]


_OPERATOR_CANCEL_ERROR = ToolCallError(
    "timeout", "Command timed out before completing."
)
"""What the model path records for an operator cancel of a tool call."""


def tool_result_to_str(result: ToolResult) -> str:
    """Convert ToolResult to string for CLI display."""
    return "\n".join(_terminal_parts(result))


def _terminal_parts(result: ToolResult) -> list[str]:
    """The lines a result renders as in the terminal (joined with newlines)."""
    if isinstance(result, str):
        return [result]
    elif isinstance(result, (int, float, bool)):
        return [str(result)]
    elif isinstance(result, ContentText):
        return [result.text]
    elif isinstance(result, list):
        # render text parts; note non-text parts rather than discarding the
        # text alongside them (the full result is preserved in the ToolEvent)
        return [
            c.text
            if isinstance(c, ContentText)
            else _omitted(getattr(c, "type", "non-text"))
            for c in result
        ]
    elif isinstance(result, ContentBase):
        # any non-text content (image, audio, video, document, data, ...) —
        # never dump raw payloads (e.g. base64 data URIs) into the terminal
        return [_omitted(result.type)]
    else:
        return [str(result)]


def _terminal_text(tool: str, parts: list[str], max_output: int | None) -> str:
    """The newline-joined parts, truncated to the tool's output limit.

    Equal to truncate_tool_output() on the full join, without building it:
    middle truncation keeps at most `limit` bytes from each end, and every
    character is at least one byte, so only the first and last `limit`
    characters of the join can appear in the output. A large structured
    result is therefore never joined or encoded whole on the event loop.
    """
    # resolved as truncate_tool_output() does (0 or less disables truncation)
    limit = max_output
    if limit is None:
        limit = active_generate_config().max_tool_output
    if limit is None:
        limit = 16 * 1024
    total = sum(len(part) for part in parts) + max(len(parts) - 1, 0)
    if limit <= 0 or total <= 2 * limit:
        text = "\n".join(parts)
    else:
        text = _join_head(parts, limit) + _join_tail(parts, limit)
    truncated = truncate_tool_output(tool, text, max_output)
    return truncated.output if truncated else text


def _join_head(parts: list[str], chars: int) -> str:
    """The first `chars` characters of the newline-joined parts."""
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if index > 0 and chars > 0:
            pieces.append("\n")
            chars -= 1
        if chars <= 0:
            break
        piece = part[:chars]
        pieces.append(piece)
        chars -= len(piece)
    return "".join(pieces)


def _join_tail(parts: list[str], chars: int) -> str:
    """The last `chars` characters of the newline-joined parts."""
    pieces: list[str] = []
    for index, part in enumerate(reversed(parts)):
        if index > 0 and chars > 0:
            pieces.append("\n")
            chars -= 1
        if chars <= 0:
            break
        piece = part[-chars:] if chars < len(part) else part
        pieces.append(piece)
        chars -= len(piece)
    return "".join(reversed(pieces))


class ToolCommand(HumanAgentCommand):
    """Command for calling tools: 'task tool <name> [args]'

    Every parameter is a named argument (task tool addition --x 12 --y 34);
    structured parameters take JSON values (task tool annotate --config '{"a": 1}').
    """

    def __init__(self, tools: list[Tool]):
        self._tools = tools
        self._failure: Exception | None = None
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
            _validate_parser_builds(tool_def)
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
    def failure(self) -> Exception | None:
        """Unexpected exception from a tool call, which must fail the sample.

        Service methods run inside the sandbox service, which turns their
        exceptions into RPC error replies and keeps serving, so raising one
        cannot end the sample. The human agent service polls this and
        raises it instead (see `run_human_agent_service()`). The first
        failure is kept.
        """
        return self._failure

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

        lines.append(_JSON_ARG_CODE)

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
        scheduler = _ToolScheduler()
        self._failure = None

        # Tool arguments arrive as a single dict, out-of-band of this
        # function's own parameters — no tool argument name can collide
        async def call_tool(tool: str, arguments: dict[str, Any] | None = None) -> str:
            kwargs = arguments or {}

            # Look up tool (unknown-tool attempts still record an event —
            # the human's failed invocation is data too)
            tool_fn = self._tool_map.get(tool)
            if tool_fn is None:
                return await self._execute_tool(tool, None, kwargs)

            # model tool calls run inside span(type="tool") — mirror that so
            # nested activity (e.g. model calls made by the tool) attributes
            # to the tool in timelines rather than to the enclosing agent
            async with scheduler.slot(parallel=bool(self._tool_defs[tool].parallel)):
                async with span(name=tool, type="tool"):
                    return await self._execute_tool(tool, tool_fn, kwargs)

        return call_tool

    async def _execute_tool(
        self, tool: str, tool_fn: Tool | None, kwargs: dict[str, Any]
    ) -> str:
        # Record the event pending, before conversion/execution, with the
        # arguments exactly as sent (they arrived as JSON so they are
        # JSON-safe by construction), then finalize it on every outcome —
        # for human baselines the human's tool usage is the data, so the
        # transcript must carry successes, tool errors, and crashes alike
        # apply the tool's custom viewer (if any) so human events render the
        # same way model-invoked events for the same tool do
        call_id = uuid()
        view = (
            tool_call_view(
                ToolCall(id=call_id, function=tool, arguments=kwargs),
                [self._tool_defs[tool]],
            )
            if tool in self._tool_defs
            else None
        )
        # operator cancellation (`inspect ctl sample cancel-tool-call`, the
        # TUI's timeout control) cancels this scope; the hook must be on the
        # event before it is published as pending
        cancel_scope = anyio.CancelScope()
        event = ToolEvent(
            id=call_id,
            function=tool,
            arguments=kwargs,
            view=view,
            pending=True,
        )
        event._set_cancel_fn(cancel_scope.cancel)
        transcript()._event(event)

        # nested waits (model calls, rate limits) are excluded from the
        # event's working time, as on the model tool path
        start = sample_clock()

        def finalize(
            result: ToolResult = "",
            error: ToolCallError | None = None,
            failed: bool | None = None,
            truncated: tuple[int, int] | None = None,
        ) -> None:
            event._set_result(
                result=result,
                truncated=truncated,
                error=error,
                working_time=sample_working_time_since(start),
                agent=None,
                failed=failed,
                message_id=None,
            )
            # publish the completion — mutation alone leaves the event
            # registered pending (stale live subscribers, pinned forever
            # in bounded transcripts)
            transcript()._event_updated(event)

        # Unknown tool: record the failed attempt and surface a clean error
        if tool_fn is None:
            finalize(error=ToolCallError("parsing", f"Unknown tool '{tool}'"))
            return _capped(tool, f"Error: Unknown tool '{tool}'", None)

        # the tool's own max_output wins over the generate config, as on
        # the model path; it bounds every reply, errors included
        max_output = self._tool_defs[tool].max_output

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
            return _capped(tool, f"Error: {validation_errors}", max_output)

        try:
            with cancel_scope:
                try:
                    # tool_params() runs typed arguments' constructors and
                    # validators (user code), so it shares the tool body's
                    # exception disposition, as on the model path
                    params = tool_params(kwargs, tool_fn)
                    result = await tool_fn(**params)
                except Exception as ex:
                    return self._tool_exception(tool, ex, max_output, finalize)
        except BaseException:
            # an outer cancellation (service teardown, sample cancel) or
            # another BaseException escapes cancel_scope, including when an
            # operator cancel of this call landed in the same turn; the
            # event must not stay pending
            if event.pending:
                finalize(
                    error=_OPERATOR_CANCEL_ERROR
                    if cancel_scope.cancel_called
                    else ToolCallError("unknown", "Tool call was cancelled.")
                )
            raise

        if cancel_scope.cancelled_caught:
            # same outcome the model path records for an operator cancel
            finalize(error=_OPERATOR_CANCEL_ERROR)
            return f"Error: {_OPERATOR_CANCEL_ERROR.message}"

        # success: shared massaging/truncation — structured content is
        # preserved in the event untruncated (the terminal rendering is
        # capped separately below)
        content, truncated = resolve_tool_content(result, tool, max_output)
        finalize(result=content, truncated=truncated)
        if isinstance(content, str):
            return content
        return _terminal_text(tool, _terminal_parts(result), max_output)

    def _tool_exception(
        self,
        tool: str,
        raw_ex: Exception,
        max_output: int | None,
        finalize: Callable[..., None],
    ) -> str:
        """Record a tool exception and apply the model path's disposition.

        Sample termination anywhere in the exception's history and limits
        propagate to the sandbox service, which enacts them. Expected tool
        errors are returned to the human. Unexpected exceptions are held as
        `failure`, which fails the sample. For an exception group, every
        leaf is considered: an unexpected leaf wins, then a limit, and only
        a group of expected errors is recoverable.
        """
        _raise_if_control_flow(raw_ex, finalize)

        ex, classified = _decisive_exception(raw_ex, tool)

        if classified is None:
            # unexpected: the model path raises these out of execute_tools()
            # and the sample fails. Reply to the human first, then let the
            # human agent service raise it.
            finalize(error=ToolCallError("unknown", str(ex)), failed=True)
            if self._failure is None:
                self._failure = ex
            message = _capped(tool, f"Error executing tool '{tool}': {ex}", max_output)
            return f"{message}\nThis is an unexpected error, so the sample will end with it."

        if isinstance(ex, LimitExceededError) and not isinstance(
            ex, OutputLimitExceededError
        ):
            # the sandbox service routes a LimitExceededError to the active
            # sample, so record (with the shared "limit" classification) and
            # propagate
            finalize(error=classified.error)
            raise ex from raw_ex

        # expected tool failure: record the shared classification and
        # surface the message (plus any partial output — sandbox
        # timeouts and output-limit hits carry one — routed through the
        # shared truncation so a 10 MiB partial can't flood anything)
        content, truncated = resolve_tool_content(classified.result, tool, max_output)
        finalize(result=content, error=classified.error, truncated=truncated)
        reply = f"Error: {classified.error.message}"
        if isinstance(classified.result, str) and classified.result:
            reply = f"{reply}\n{classified.result}"
        return _capped(tool, reply, max_output)


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


def _boolean_argument_lines(parser_var: str, name: str, info: ParamInfo) -> list[str]:
    """Generated code for a boolean parameter: --<name> and --no-<name>.

    Each flag stores an explicit constant, so a parameter whose own name
    starts with `no_` still gets an unambiguous pair (`no_cache` gets
    --no-cache for true and --no-no-cache for false). argparse's
    BooleanOptionalAction infers false from a --no- prefix instead, and
    Python 3.14 rejects it outright for such options. The flags (plus
    --null-<name> for a nullable parameter) form a mutually exclusive group
    that carries requiredness. Absent flags are suppressed from the
    namespace so the tool's own default applies.
    """
    arg_name = name.replace("_", "-")
    dest = f"arg_{name}"
    flags: list[tuple[str, bool | None, str]] = [
        (f"--{arg_name}", True, _help(info.description or "")),
        (f"--no-{arg_name}", False, _help(f"send false for {name}")),
    ]
    if info.is_optional:
        flags.append((f"--null-{arg_name}", None, _help(f"send null for {name}")))
    lines = [
        f"_group = {parser_var}.add_mutually_exclusive_group("
        f"required={info.is_required})"
    ]
    for flag, const, flag_help in flags:
        help_part = f", help={flag_help!r}" if flag_help else ""
        lines.append(
            f"_group.add_argument({flag!r}, dest={dest!r}, "
            f"action='store_const', const={const!r}, "
            f"default=argparse.SUPPRESS{help_part})"
        )
    return lines


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
    lines.append(
        f"{parser_var} = tool_subparsers.add_parser({tool_name!r}, "
        f"help={_help(tool_description)!r}, "
        f"formatter_class=argparse.RawDescriptionHelpFormatter)"
    )

    # Generate arguments in declaration order (all as named args)
    for name, info in param_infos.items():
        arg_name = name.replace("_", "-")

        if info.schema_type == "boolean":
            lines.extend(_boolean_argument_lines(parser_var, name, info))
            continue

        parts: list[str] = []

        # Always use named args (--x, --y); dests are prefixed so tool
        # argument names can never shadow the parser's routing dests
        # ('command', 'tool_name')
        parts.append(repr(f"--{arg_name}"))
        parts.append(f"dest={f'arg_{name}'!r}")

        # Type conversion (values are always literal — explicit null travels
        # via the dedicated --null-<name> flag, so no token is magic)
        if info.schema_type == "integer":
            parts.append("type=int")
        elif info.schema_type == "number":
            parts.append("type=float")
        elif info.schema_type == "json":
            # structured parameter: the flag's value is JSON ('null' included)
            parts.append("type=_json_arg")
            parts.append('metavar="JSON"')

        # Enum/choices
        if info.enum:
            parts.append(f"choices={info.enum!r}")
        elif info.schema_type != "json":
            # metavar must come from the parameter name — argparse would
            # otherwise derive it from the internal prefixed dest (ARG_X)
            parts.append(f"metavar={name.upper()!r}")

        # Required/default: nullability and requiredness are independent —
        # null is an accepted *value*, it doesn't make the flag omittable
        # (a required nullable parameter becomes a required mutually
        # exclusive group below). Absent optional flags are suppressed
        # entirely so the handler can distinguish "not provided" from an
        # explicit null
        if info.is_required and not info.is_optional:
            parts.append("required=True")
        else:
            parts.append("default=argparse.SUPPRESS")

        # Help text (structured params get an example instance, validated
        # against the schema)
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
        if help_text:
            parts.append(f"help={_help(help_text)!r}")

        if info.is_optional:
            # every nullable parameter gets a dedicated --null-<name> flag —
            # one uniform null spelling across all types (booleans included),
            # leaving every value token literal. Mutually exclusive with the
            # value flag; the group carries requiredness for required
            # nullable parameters
            lines.append(
                f"_group = {parser_var}.add_mutually_exclusive_group("
                f"required={info.is_required})"
            )
            lines.append(f"_group.add_argument({', '.join(parts)})")
            lines.append(
                f"_group.add_argument({f'--null-{arg_name}'!r}, "
                f"dest={f'arg_{name}'!r}, action='store_const', const=None, "
                f"default=argparse.SUPPRESS, "
                f"help={_help(f'send null for {name}')!r})"
            )
        else:
            lines.append(f"{parser_var}.add_argument({', '.join(parts)})")

    parser_code = "\n".join(lines)
    return parser_code, has_complex_params
