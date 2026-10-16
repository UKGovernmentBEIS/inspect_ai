import argparse
from dataclasses import dataclass

import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._human.commands.tool import ToolCommand, tool_result_to_str
from inspect_ai.agent._human.state import HumanAgentState
from inspect_ai.tool import ToolDef, ToolError, tool
from inspect_ai.util import JSONSchema


def _agent_state() -> HumanAgentState:
    """Human agent state for ToolCommand.service(), which does not read it."""
    return HumanAgentState(instructions="")


# Test tool_result_to_str() with various ToolResult types
def test_tool_result_to_str_string():
    assert tool_result_to_str("hello") == "hello"


def test_tool_result_to_str_int():
    assert tool_result_to_str(42) == "42"


def test_tool_result_to_str_float():
    assert tool_result_to_str(3.14) == "3.14"


def test_tool_result_to_str_bool():
    assert tool_result_to_str(True) == "True"


def test_tool_result_to_str_content_text():
    assert tool_result_to_str(ContentText(text="hello")) == "hello"


def test_tool_result_to_str_list_content_text():
    result = tool_result_to_str([ContentText(text="a"), ContentText(text="b")])
    assert result == "a\nb"


def test_tool_result_to_str_empty_list():
    assert tool_result_to_str([]) == ""


def test_tool_result_to_str_list_with_image_keeps_text():
    out = tool_result_to_str([ContentText(text="a"), ContentImage(image="base64data")])
    assert out.splitlines()[0] == "a"


# =============================================================================
# Landing tests (2026-08-18): failing-first tests for the merge blockers.
# Each exercises a behavioral seam; see PR review for the corresponding fix.
# =============================================================================


@tool
def _format_text():
    async def execute(text: str, uppercase: bool = False, reverse: bool = True) -> str:
        """Format text with various options.

        Args:
            text: The text to format.
            uppercase: Whether to convert to uppercase.
            reverse: Whether to reverse the text.

        Returns:
            The formatted text.
        """
        result = text
        if uppercase:
            result = result.upper()
        if reverse:
            result = result[::-1]
        return result

    return execute


@tool
def _addition():
    async def execute(x: int, y: int) -> int:
        """Add two numbers.

        Args:
            x: First number.
            y: Second number.

        Returns:
            The sum.
        """
        return x + y

    return execute


@tool
def _process_config():
    async def execute(config: dict, name: str) -> str:
        """Process a configuration object.

        Args:
            config: Configuration dictionary with settings.
            name: Name for the configuration.

        Returns:
            A summary.
        """
        return f"{name}: {len(config)} settings"

    return execute


def _build_parsers(tools: list) -> tuple[argparse.ArgumentParser, dict]:
    """Exec the generated parser code the way the sandbox script does."""
    command = ToolCommand(tools)
    parser = argparse.ArgumentParser(prog="task.py")
    subparsers = parser.add_subparsers(dest="command")
    namespace: dict = {"subparsers": subparsers, "argparse": argparse}
    exec(compile(command.get_cli_parser_code(), "<generated>", "exec"), namespace)
    return parser, namespace


def _handler_kwargs(parser: argparse.ArgumentParser, argv: list[str]) -> dict:
    """Mirror the generated handler's tool-args extraction (absent = suppressed)."""
    args = parser.parse_args(argv)
    return {k[len("arg_") :]: v for k, v in vars(args).items() if k.startswith("arg_")}


# --- blocker 1: booleans must preserve the tool's own defaults ---------------


def test_boolean_absent_flag_preserves_tool_default() -> None:
    """A bool param not mentioned on the CLI must not be sent to the tool.

    Sending False for an absent flag silently overrides a tool-side
    default of True (`reverse: bool = True` becomes False on every bare
    invocation) — the human's call diverges from a model's identical call.
    """
    parser, _ = _build_parsers([_format_text()])
    kwargs = _handler_kwargs(parser, ["tool", "_format_text", "--text", "hi"])
    assert "uppercase" not in kwargs
    assert "reverse" not in kwargs


def test_boolean_false_is_expressible() -> None:
    """--no-<flag> must exist so False can be passed explicitly."""
    parser, _ = _build_parsers([_format_text()])
    kwargs = _handler_kwargs(
        parser, ["tool", "_format_text", "--text", "hi", "--no-reverse"]
    )
    assert kwargs.get("reverse") is False


# --- blocker 2: human tool invocations must record a ToolEvent ---------------


@pytest.mark.anyio
async def test_service_records_tool_event() -> None:
    """The service handler must leave a ToolEvent in the transcript.

    For human baselines the human's tool usage is the data; a transcript
    that omits it under-reports the action space exercised.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    command = ToolCommand([_addition()])
    handler = command.service(state=_agent_state())

    init_transcript(Transcript())
    result = await handler(tool="_addition", arguments={"x": 1, "y": 2})
    assert result == "3"

    tool_events = [e for e in transcript().events if e.event == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0].function == "_addition"
    assert tool_events[0].arguments == {"x": 1, "y": 2}
    # scalar results are stringified exactly as model tool events record them
    assert tool_events[0].result == "3"


# --- blocker 3: tool names must be valid identifiers and unique --------------


def _named_tool(name: str):
    async def execute() -> str:
        """Do a thing.

        Returns:
            A thing.
        """
        return "thing"

    return ToolDef(
        execute, name=name, description="Do a thing.", parameters={}
    ).as_tool()


def test_dashed_tool_name_generates_working_cli() -> None:
    """Inspect accepts tool names like find-item; the human CLI must too.

    Only the generated Python variable needed an identifier — the
    subparser name is a quoted literal. Rejecting such names gave the
    human a smaller tool set than the model.
    """
    parser, _ = _build_parsers([_named_tool("find-item")])
    args = parser.parse_args(["tool", "find-item"])
    assert args.tool_name == "find-item"


@pytest.mark.anyio
async def test_dashed_tool_name_service_roundtrip() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript

    handler = ToolCommand([_named_tool("find-item")]).service(state=_agent_state())
    init_transcript(Transcript())
    assert await handler(tool="find-item", arguments={}) == "thing"


def test_empty_tool_name_unreachable() -> None:
    """ToolDef substitutes the function name for an empty tool name.

    So the empty-name guard in ToolCommand is defensive only — this
    documents that the public API can't reach it.
    """
    command = ToolCommand([_named_tool("")])
    assert "execute" in command._tool_defs


def test_duplicate_tool_names_rejected() -> None:
    """Two tools with the same name silently last-win today."""
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        ToolCommand([_named_tool("same_name"), _named_tool("same_name")])


# --- should-fix: mixed content results keep their text -----------------------


def test_mixed_content_preserves_text() -> None:
    """Text alongside an image should render the text, not raise it away."""
    out = tool_result_to_str([ContentText(text="findings"), ContentImage(image="b64")])
    assert "findings" in out
    assert "omitted" in out


def test_pure_image_returns_friendly_message() -> None:
    """Non-text-only results should explain themselves, not traceback."""
    out = tool_result_to_str(ContentImage(image="b64"))
    assert "omitted" in out


# --- per-param JSON: complex params are ordinary flags with JSON values -----


def test_mixed_tool_simple_params_are_flags() -> None:
    """A tool with one complex param keeps CLI flags for its simple params."""
    parser, _ = _build_parsers([_process_config()])
    kwargs = _handler_kwargs(
        parser,
        ["tool", "_process_config", "--name", "test", "--config", '{"a": 1, "b": 2}'],
    )
    assert kwargs["name"] == "test"
    assert kwargs["config"] == {"a": 1, "b": 2}


def test_complex_param_invalid_json_errors_cleanly() -> None:
    """Malformed JSON for a complex param fails at parse time, naming the flag."""
    parser, _ = _build_parsers([_process_config()])
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            ["tool", "_process_config", "--name", "t", "--config", "{not json"]
        )
    assert exc_info.value.code == 2  # argparse usage error, not a traceback


def test_complex_param_help_shows_example_instance() -> None:
    """Help for a complex param shows a copy-pasteable JSON example, not a schema."""
    _, namespace = _build_parsers([_process_config()])
    sub = namespace["tool_subparsers"].choices["_process_config"]
    help_text = sub.format_help()
    assert "--config" in help_text
    assert "--name" in help_text
    # an example instance, not JSON-Schema vocabulary
    assert '"additionalProperties"' not in help_text
    assert "JSON" in help_text


def test_required_complex_param_enforced_by_argparse() -> None:
    """Omitting a required complex param is an immediate argparse error."""
    parser, _ = _build_parsers([_process_config()])
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["tool", "_process_config", "--name", "t"])
    assert exc_info.value.code == 2


# =============================================================================
# Review findings (2026-08-20): failing-first tests for the five issues found
# in the final pre-merge review pass.
# =============================================================================

# --- finding 3: parameter names must not collide with parser/service routing


@tool
def _shadowing_params():
    async def execute(command: str, tool_name: str) -> str:
        """Echo parameters whose names shadow parser routing dests.

        Args:
            command: Shadows the top-level dispatch dest.
            tool_name: Shadows the tool-selection dest.

        Returns:
            The combined values.
        """
        return f"{command}/{tool_name}"

    return execute


def _handler_call(parser: argparse.ArgumentParser, argv: list[str]) -> tuple[str, dict]:
    """Mirror the generated handler: routing dests vs prefixed tool-arg dests."""
    args = parser.parse_args(argv)
    tool_name = getattr(args, "tool_name", None) or ""
    tool_args = {
        k[len("arg_") :]: v
        for k, v in vars(args).items()
        if k.startswith("arg_") and v is not None
    }
    return tool_name, tool_args


def test_params_shadowing_routing_names_route_correctly() -> None:
    """Params named `command`/`tool_name` must not hijack dispatch.

    Today `--tool-name n` overwrites the selected subcommand (the tool
    lookup then fails) and `--command c` overwrites top-level dispatch
    (the tool handler never runs).
    """
    parser, _ = _build_parsers([_shadowing_params()])
    args = parser.parse_args(
        ["tool", "_shadowing_params", "--command", "c", "--tool-name", "n"]
    )
    assert args.command == "tool"  # top-level dispatch intact
    tool_name, tool_args = _handler_call(
        parser, ["tool", "_shadowing_params", "--command", "c", "--tool-name", "n"]
    )
    assert tool_name == "_shadowing_params"  # tool selection intact
    assert tool_args == {"command": "c", "tool_name": "n"}


def test_prefixed_dests_do_not_leak_into_help() -> None:
    """Help metavars show the parameter name, not the internal dest.

    The collision-proof arg_ dest prefix must stay invisible: help must
    read `--x X`, not `--x ARG_X`.
    """
    _, namespace = _build_parsers([_addition()])
    help_text = namespace["tool_subparsers"].choices["_addition"].format_help()
    assert "--x X" in help_text
    assert "ARG_" not in help_text


@pytest.mark.anyio
async def test_service_accepts_any_identifier_param_name() -> None:
    """The service transports tool args out-of-band of its own params.

    Passing tool args as **kwargs next to the tool-name param means a
    tool parameter named `_tool_name_` is a duplicate-keyword TypeError.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript

    async def execute(_tool_name_: str) -> str:
        """Echo a hostile parameter name.

        Args:
            _tool_name_: Parameter named after the old routing kwarg.

        Returns:
            The value.
        """
        return _tool_name_

    hostile = ToolDef(
        execute,
        name="hostile",
        description="Echo a hostile parameter name.",
        parameters={"_tool_name_": "Parameter named after the old routing kwarg."},
    ).as_tool()

    command = ToolCommand([hostile])
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="hostile", arguments={"_tool_name_": "ok"})
    assert result == "ok"


# --- round 2: explicit JSON null must be expressible ------------------------


@tool
def _namer():
    async def execute(name: str | None = None) -> str:
        """Greet by name.

        Args:
            name: A nullable name.

        Returns:
            A greeting.
        """
        return f"hi {name}"

    return execute


@tool
def _maybe():
    async def execute(value: int | None = None, config: dict | None = None) -> str:
        """Accept nullable parameters.

        Args:
            value: A nullable integer.
            config: A nullable configuration object.

        Returns:
            A rendering of what was received.
        """
        return f"{value}/{config}"

    return execute


def test_explicit_null_for_structured_param_is_sent() -> None:
    """--config null must send {"config": None}, not silently drop it.

    The handler's None filter conflated "absent" with "explicit null",
    so a null a model could send was unsendable by the human.
    """
    parser, _ = _build_parsers([_maybe()])
    kwargs = _handler_kwargs(parser, ["tool", "_maybe", "--config", "null"])
    assert kwargs == {"config": None}


def test_explicit_null_via_dedicated_flag() -> None:
    """--null-<name> sends an explicit JSON null for any nullable parameter."""
    parser, _ = _build_parsers([_maybe()])
    kwargs = _handler_kwargs(parser, ["tool", "_maybe", "--null-value"])
    assert kwargs == {"value": None}


def test_nullable_string_keeps_null_as_literal_text() -> None:
    """String values are always literal — the token null is the string "null".

    The converter approach mapped the only natural spelling of the
    string "null" to None, making a schema-valid value inexpressible;
    with a dedicated null flag, no token is magic.
    """
    parser, _ = _build_parsers([_namer()])
    kwargs = _handler_kwargs(parser, ["tool", "_namer", "--name", "null"])
    assert kwargs == {"name": "null"}
    kwargs = _handler_kwargs(parser, ["tool", "_namer", "--null-name"])
    assert kwargs == {"name": None}


def test_value_and_null_flag_are_mutually_exclusive() -> None:
    parser, _ = _build_parsers([_maybe()])
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["tool", "_maybe", "--value", "3", "--null-value"])
    assert exc_info.value.code == 2


def test_absent_optional_params_stay_absent() -> None:
    """Absence still means absence — the tool's own defaults apply."""
    parser, _ = _build_parsers([_maybe()])
    assert _handler_kwargs(parser, ["tool", "_maybe"]) == {}


def test_nullable_scalar_still_accepts_values() -> None:
    parser, _ = _build_parsers([_maybe()])
    kwargs = _handler_kwargs(parser, ["tool", "_maybe", "--value", "3"])
    assert kwargs == {"value": 3}


# --- round 2: help examples must be schema-valid -----------------------------


def test_example_instance_includes_all_required_properties() -> None:
    """The 'copy-pasteable' example must satisfy the schema it illustrates.

    Truncating an object example to its first two properties can drop
    required ones — help then shows an example the service rejects.
    """
    from inspect_ai.agent._human.commands.tool import _example_instance

    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "string"},
            "c": {"type": "string"},
            "d": {"type": "string"},
        },
        "required": ["a", "b", "c"],
    }
    example = _example_instance(schema)
    assert {"a", "b", "c"} <= set(example.keys())


# --- round 2: human tool execution runs inside a tool span -------------------


@pytest.mark.anyio
async def test_tool_execution_runs_in_tool_span() -> None:
    """Human tool calls get a span(type="tool") like model tool calls.

    Without it, nested activity (e.g. model calls made by the tool)
    appears as top-level human-agent activity in timelines.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_addition()]).service(state=_agent_state())
    init_transcript(Transcript())
    await handler(tool="_addition", arguments={"x": 1, "y": 2})

    spans = [e for e in transcript().events if e.event == "span_begin"]
    assert any(s.type == "tool" and s.name == "_addition" for s in spans)
    tool_event = next(e for e in transcript().events if e.event == "tool")
    tool_span = next(s for s in spans if s.type == "tool")
    assert tool_event.span_id == tool_span.id


# --- round 3: Optional[...] descriptions live on the outer anyOf schema ------


def test_optional_param_keeps_outer_description() -> None:
    """Pydantic puts Optional[T] descriptions on the outer anyOf schema.

    Recursing into the non-null branch dropped them, so generated help
    lost the parameter's docstring text for every nullable parameter.
    """
    from inspect_ai.agent._human.commands.tool import _classify_schema

    info = _classify_schema(
        {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": "The retry budget.",
            "default": 3,
        }
    )
    assert info.is_optional
    assert info.description == "The retry budget."
    assert info.default == 3


# --- round 3: a tool named `tool` must not shadow the parent parser ----------


def test_tool_named_tool_does_not_shadow_parent_parser() -> None:
    """Generated parser variables must not collide with the parent's.

    A tool literally named `tool` generated `tool_parser = ...`,
    overwriting the parent parser variable — bare `task tool` then
    printed that tool's help instead of listing all tools.
    """
    parser, namespace = _build_parsers([_named_tool("tool")])
    child = namespace["tool_subparsers"].choices["tool"]
    assert namespace["tool_parser"] is not child
    args = parser.parse_args(["tool", "tool"])
    assert args.tool_name == "tool"


# --- round 6: handoff() agent tools are rejected, not silently broken --------


def test_handoff_tool_rejected_at_construction() -> None:
    """handoff() returns an AgentTool, which satisfies list[Tool].

    The model path routes it through agent_handoff(); the human path
    would call it directly, which unconditionally raises. Reject at
    construction with a clear message instead of advertising a command
    that always fails.
    """
    from inspect_ai.agent import AgentState, agent, handoff

    @agent
    def helper():
        async def execute(state: AgentState) -> AgentState:
            """Help with the task.

            Args:
                state: Agent state.

            Returns:
                The state.
            """
            return state

        return execute

    with pytest.raises(ValueError, match="handoff"):
        ToolCommand([handoff(helper())])


# --- round 6: arrays take JSON values so every valid value is expressible ----


@tool
def _tagger():
    async def execute(tags: list[str]) -> str:
        """Count tags.

        Args:
            tags: The tags.

        Returns:
            The count.
        """
        return str(len(tags))

    return execute


def test_array_values_are_json_and_lossless() -> None:
    """Space-separated arrays could not express option-looking items.

    With nargs="*", ["-a", "-b"] had no CLI spelling (tokens parse as
    options; --tags=-x keeps only the last; -- does not help within the
    argument) and the empty list also had no append-style spelling.
    JSON values express every schema-valid array.
    """
    parser, _ = _build_parsers([_tagger()])
    kwargs = _handler_kwargs(parser, ["tool", "_tagger", "--tags", '["-a", "-b"]'])
    assert kwargs == {"tags": ["-a", "-b"]}
    kwargs = _handler_kwargs(parser, ["tool", "_tagger", "--tags", "[]"])
    assert kwargs == {"tags": []}


# --- round 6: percent signs in descriptions must not break argparse ----------


@tool
def _percenter():
    async def execute(threshold: float) -> str:
        """Return 100% of matches.

        Args:
            threshold: A 50% cutoff.

        Returns:
            A marker.
        """
        return "ok"

    return execute


def test_percent_in_descriptions_survives_help_rendering() -> None:
    """Argparse percent-interpolates help text at formatting time.

    repr() makes the generated source safe but a bare % in a tool or
    parameter description still raises at `task tool` / `--help` time.
    """
    parser, namespace = _build_parsers([_percenter()])
    listing = namespace["tool_parser"].format_help()
    assert "100% of matches" in listing
    tool_help = namespace["tool_subparsers"].choices["_percenter"].format_help()
    assert "50% cutoff" in tool_help


# --- round 7: non-parallel tools are serialized under concurrent requests ----


def _tracking_tool(parallel: bool):
    import anyio

    active = {"now": 0, "max": 0}

    async def execute() -> str:
        """Track concurrent executions.

        Returns:
            A marker.
        """
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await anyio.sleep(0.05)
        active["now"] -= 1
        return "ok"

    tool = ToolDef(
        execute,
        name="tracker",
        description="Track concurrency.",
        parameters={},
        parallel=parallel,
    ).as_tool()
    return tool, active


@pytest.mark.anyio
async def test_non_parallel_tool_serialized() -> None:
    """Tools declaring parallel=False execute serially.

    SandboxService handles request files concurrently, so two shell
    invocations can enter the handler at once.
    """
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript

    tool, active = _tracking_tool(parallel=False)
    handler = ToolCommand([tool]).service(state=_agent_state())
    init_transcript(Transcript())

    async def call() -> None:
        await handler(tool="tracker")

    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        tg.start_soon(call)
    assert active["max"] == 1


@pytest.mark.anyio
async def test_parallel_tool_stays_concurrent() -> None:
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript

    tool, active = _tracking_tool(parallel=True)
    handler = ToolCommand([tool]).service(state=_agent_state())
    init_transcript(Transcript())

    async def call() -> None:
        await handler(tool="tracker")

    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        tg.start_soon(call)
    assert active["max"] == 2


# --- invariant: human events carry the shared classification -----------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: TimeoutError(),
        lambda: PermissionError(13, "Permission denied", "/etc/shadow"),
        lambda: FileNotFoundError(2, "No such file", "missing.txt"),
        lambda: IsADirectoryError(21, "Is a directory", "/tmp"),
        lambda: UnicodeDecodeError("utf-8", b"", 0, 1, "invalid start byte"),
        lambda: ToolError("expected failure"),
    ],
    ids=[
        "timeout",
        "permission",
        "file_not_found",
        "is_a_directory",
        "unicode",
        "tool_error",
    ],
)
async def test_human_event_error_matches_shared_classification(exc_factory) -> None:
    """The human ToolEvent carries exactly the shared classification.

    This is the anti-drift invariant: for any classified exception, the
    human path records the same ToolCallError the model path would.
    """
    from inspect_ai.model._call_tools import classify_tool_exception

    expected = classify_tool_exception(exc_factory(), "raiser")
    assert expected is not None

    _, event = await _invoke_raising(exc_factory)
    assert event.error is not None
    assert event.error.type == expected.error.type
    assert event.error.message == expected.error.message
    assert event.failed is None  # classified failures are expected outcomes


@pytest.mark.anyio
async def test_sandbox_unavailable_classified() -> None:
    from inspect_ai.util._sandbox.environment import SandboxUnavailableError

    result, event = await _invoke_raising(
        lambda: SandboxUnavailableError("container gone")
    )
    assert event.error is not None and event.error.type == "sandbox_unavailable"
    assert event.failed is None


@pytest.mark.anyio
async def test_limit_events_typed_limit() -> None:
    """Limit violations record error.type='limit' (they were 'unknown')."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.util._limit import LimitExceededError

    async def execute() -> str:
        """Exceed a limit.

        Returns:
            Never returns.
        """
        raise LimitExceededError("token", value=1001, limit=1000)

    limited = ToolDef(
        execute, name="limited", description="Exceed a limit.", parameters={}
    ).as_tool()
    handler = ToolCommand([limited]).service(state=_agent_state())
    init_transcript(Transcript())
    with pytest.raises(LimitExceededError):
        await handler(tool="limited", arguments={})
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.error is not None and event.error.type == "limit"


@pytest.mark.anyio
async def test_output_limit_partial_is_capped() -> None:
    """A huge output-limit partial routes through the shared output cap."""
    from inspect_ai.util import OutputLimitExceededError

    big_partial = "x" * (64 * 1024)
    result, event = await _invoke_raising(
        lambda: OutputLimitExceededError("10 MiB", big_partial)
    )
    assert event.error is not None and event.error.type == "limit"
    assert event.truncated is not None
    assert len(str(result)) < 64 * 1024


@pytest.mark.anyio
async def test_cancellation_finalizes_event() -> None:
    """Cancelling a running tool must not leave its event pending forever."""
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    started = anyio.Event()

    async def execute() -> str:
        """Sleep until cancelled.

        Returns:
            Never returns.
        """
        started.set()
        await anyio.sleep(30)
        return "unreachable"

    sleeper = ToolDef(
        execute, name="sleeper", description="Sleep.", parameters={}
    ).as_tool()
    handler = ToolCommand([sleeper]).service(state=_agent_state())
    init_transcript(Transcript())

    async def call() -> None:
        await handler(tool="sleeper", arguments={})

    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        await started.wait()
        tg.cancel_scope.cancel()

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.pending is None  # finalized
    assert [e for e in transcript().pending_events if e.event == "tool"] == []


@pytest.mark.anyio
async def test_structured_event_content_survives_terminal_capping() -> None:
    """Large structured results keep their content list in the event."""
    from inspect_ai._util.content import ContentImage, ContentText
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> list:
        """Return large structured content.

        Returns:
            Text and an image.
        """
        return [ContentText(text="x" * (64 * 1024)), ContentImage(image="b64")]

    structured = ToolDef(
        execute, name="structured", description="Structured.", parameters={}
    ).as_tool()
    handler = ToolCommand([structured]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="structured", arguments={})

    event = next(e for e in transcript().events if e.event == "tool")
    assert isinstance(event.result, list)
    assert any(getattr(c, "type", "") == "image" for c in event.result)
    assert len(str(result)) < 64 * 1024  # terminal rendering capped


# --- round 8: parallel=False is a global barrier, not per-tool ---------------


def _named_tracking_tool(name: str, parallel: bool, active: dict):
    import anyio

    async def execute() -> str:
        """Track concurrent executions.

        Returns:
            A marker.
        """
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await anyio.sleep(0.05)
        active["now"] -= 1
        return "ok"

    return ToolDef(
        execute,
        name=name,
        description="Track concurrency.",
        parameters={},
        parallel=parallel,
    ).as_tool()


async def _run_concurrently(handler, *tools: str) -> None:
    import anyio

    async with anyio.create_task_group() as tg:
        for name in tools:

            async def call(n: str = name) -> None:
                await handler(tool=n)

            tg.start_soon(call)


@pytest.mark.anyio
async def test_two_distinct_serial_tools_do_not_overlap() -> None:
    """parallel=False means no concurrency with ANY tool call.

    Per-tool locks let two different non-parallel tools overlap
    (max_active reached 2 in the reviewer's repro); the model path makes
    each serial call its own execution stage — a global barrier.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript

    active = {"now": 0, "max": 0}
    command = ToolCommand(
        [
            _named_tracking_tool("serial_a", False, active),
            _named_tracking_tool("serial_b", False, active),
        ]
    )
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    await _run_concurrently(handler, "serial_a", "serial_b")
    assert active["max"] == 1


@pytest.mark.anyio
async def test_serial_tool_barriers_parallel_tool() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript

    active = {"now": 0, "max": 0}
    command = ToolCommand(
        [
            _named_tracking_tool("serial_a", False, active),
            _named_tracking_tool("par_b", True, active),
        ]
    )
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    await _run_concurrently(handler, "serial_a", "par_b")
    assert active["max"] == 1


# --- round 7: custom tool viewers apply to human ToolEvents -------------------


@pytest.mark.anyio
async def test_custom_viewer_applies_to_human_tool_events() -> None:
    """A tool's ToolCallViewer must shape human events as it does model ones.

    view was never built, so the same tool recorded a custom rendering
    when model-invoked and view=None when human-invoked — the transcript
    rendered them differently.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.tool import ToolCall, ToolCallContent, ToolCallView

    def viewer(call: ToolCall) -> ToolCallView:
        return ToolCallView(
            call=ToolCallContent(
                format="markdown", content=f"**adding** {call.arguments}"
            )
        )

    async def execute(x: int, y: int) -> int:
        """Add.

        Args:
            x: First.
            y: Second.

        Returns:
            Sum.
        """
        return x + y

    viewed = ToolDef(
        execute,
        name="viewed",
        description="Add.",
        parameters={"x": "First.", "y": "Second."},
        viewer=viewer,
    ).as_tool()

    handler = ToolCommand([viewed]).service(state=_agent_state())
    init_transcript(Transcript())
    await handler(tool="viewed", arguments={"x": 1, "y": 2})

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.view is not None
    assert "adding" in event.view.content


# --- round 7: sample waiting time is excluded from tool working time ---------


@pytest.mark.anyio
async def test_waiting_time_excluded_from_working_time() -> None:
    """Nested waits (model calls, rate limits) are not tool working time.

    The model path computes working time with sample_working_time_since()
    from a sample-clock start; a nested 50ms reported wait must not count
    as work.
    """
    import time

    from inspect_ai._util.working import (
        init_sample_working_time,
        report_sample_waiting_time,
    )
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    # waits are only tracked inside a sample
    init_sample_working_time(time.monotonic())

    async def execute() -> str:
        """Wait on something reported as sample waiting.

        Returns:
            A marker.
        """
        import anyio

        await anyio.sleep(0.06)
        report_sample_waiting_time(0.05)
        return "ok"

    waiter = ToolDef(
        execute, name="waiter", description="Report waiting time.", parameters={}
    ).as_tool()

    handler = ToolCommand([waiter]).service(state=_agent_state())
    init_transcript(Transcript())
    await handler(tool="waiter", arguments={})

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.working_time is not None
    assert 0 <= event.working_time < 0.04  # ~0.06 elapsed minus 0.05 waited


# --- drift sweep: mirror the model path's exception taxonomy -----------------


def _raising_tool(name: str, exc_factory):
    async def execute() -> str:
        """Raise a specific exception.

        Returns:
            Never returns.
        """
        raise exc_factory()

    return ToolDef(
        execute, name=name, description="Raise an exception.", parameters={}
    ).as_tool()


async def _invoke_raising(exc_factory) -> tuple:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_raising_tool("raiser", exc_factory)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())
    result = await handler(tool="raiser", arguments={})
    event = next(e for e in transcript().events if e.event == "tool")
    return result, event


@pytest.mark.anyio
async def test_tool_error_in_task_group_surfaces_cleanly() -> None:
    """Exception groups are normalized before classification.

    As on the model path — a ToolError from a task-group child is an
    expected failure, not an 'unhandled errors in a TaskGroup' hard error.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> str:
        """Raise ToolError from a task-group child.

        Returns:
            Never returns.
        """

        async def child() -> None:
            raise ToolError("expected failure")

        import anyio

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        return "unreachable"

    grouped = ToolDef(
        execute, name="grouped", description="Group ToolError.", parameters={}
    ).as_tool()
    handler = ToolCommand([grouped]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="grouped", arguments={})
    assert "expected failure" in str(result)
    assert "TaskGroup" not in str(result)
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.failed is None


@pytest.mark.anyio
async def test_file_not_found_classified() -> None:
    result, event = await _invoke_raising(
        lambda: FileNotFoundError(2, "No such file", "missing.txt")
    )
    assert event.error is not None and event.error.type == "file_not_found"
    assert "missing.txt" in str(result)
    assert event.failed is None


@pytest.mark.anyio
async def test_timeout_classified() -> None:
    result, event = await _invoke_raising(lambda: TimeoutError())
    assert event.error is not None and event.error.type == "timeout"
    assert "timed out" in str(result)


@pytest.mark.anyio
async def test_output_limit_returns_truncated_output() -> None:
    """An output-limit hit is a truncated result, not a failure."""
    from inspect_ai.util import OutputLimitExceededError

    result, event = await _invoke_raising(
        lambda: OutputLimitExceededError("1 KiB", "partial output here")
    )
    assert event.error is not None and event.error.type == "limit"
    assert event.result == "partial output here"
    assert "partial output here" in str(result)


@pytest.mark.anyio
async def test_terminate_errors_propagate() -> None:
    """Control-flow terminations must not be stringified."""
    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.log._transcript import Transcript, init_transcript

    handler = ToolCommand(
        [_raising_tool("terminator", lambda: TerminateSampleError("operator kill"))]
    ).service(state=_agent_state())
    init_transcript(Transcript())
    with pytest.raises(TerminateSampleError):
        await handler(tool="terminator", arguments={})


# --- drift sweep: results are truncated like model tool results --------------


@pytest.mark.anyio
async def test_oversize_result_truncated_in_event_and_terminal() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> str:
        """Return a huge result.

        Returns:
            A very long string.
        """
        return "x" * (64 * 1024)

    big = ToolDef(
        execute, name="big", description="Huge output.", parameters={}
    ).as_tool()
    handler = ToolCommand([big]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="big", arguments={})

    assert len(str(result)) < 64 * 1024
    assert "truncated" in str(result)
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.truncated is not None


# --- drift sweep: unknown-tool invocations are recorded ----------------------


@pytest.mark.anyio
async def test_unknown_tool_records_event() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_addition()]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="nope", arguments={"x": 1})
    assert "Unknown tool" in str(result)
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].function == "nope"
    assert events[0].error is not None and events[0].error.type == "parsing"


# --- round 7: limit failures wrapped by task groups still end the sample -----


@pytest.mark.anyio
async def test_limit_exceeded_inside_task_group_reraises() -> None:
    """A LimitExceededError raised by a task-group child must still propagate.

    AnyIO wraps child exceptions in an ExceptionGroup, which the generic
    handler caught and stringified — the sample ran past its limit. The
    inner limit error must be extracted (nested groups included) and
    re-raised so the sandbox-service boundary can end the sample.
    """
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.util._limit import LimitExceededError

    async def execute() -> str:
        """Exceed a limit inside a task group.

        Returns:
            Never returns.
        """

        async def child() -> None:
            raise LimitExceededError("token", value=1001, limit=1000)

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        return "unreachable"

    grouped = ToolDef(
        execute, name="grouped", description="Exceed a limit in a group.", parameters={}
    ).as_tool()

    handler = ToolCommand([grouped]).service(state=_agent_state())
    init_transcript(Transcript())
    with pytest.raises(LimitExceededError):
        await handler(tool="grouped", arguments={})

    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1 and events[0].error is not None


# --- round 6: limit violations must reach the sample boundary -----------------


@pytest.mark.anyio
async def test_limit_exceeded_reraises_after_recording() -> None:
    """LimitExceededError must propagate to the sandbox-service boundary.

    The boundary routes it to sample_active().limit_exceeded(), which
    ends the sample; the generic exception handler was converting limit
    violations into CLI strings, so evals ran past configured limits.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.util._limit import LimitExceededError

    async def execute() -> str:
        """Exceed a limit.

        Returns:
            Never returns.
        """
        raise LimitExceededError("token", value=1001, limit=1000)

    limited = ToolDef(
        execute, name="limited", description="Exceed a limit.", parameters={}
    ).as_tool()

    handler = ToolCommand([limited]).service(state=_agent_state())
    init_transcript(Transcript())
    with pytest.raises(LimitExceededError):
        await handler(tool="limited", arguments={})

    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None
    assert events[0].pending is None  # finalized before propagating


# --- round 5: option-like tool names have no portable spelling — reject ------


def test_option_like_tool_name_rejected_at_construction() -> None:
    """A tool name with a leading dash is rejected host-side.

    argparse treats leading-dash tokens as options, and the `--`
    separator only routes subcommands correctly on Python >= 3.13 —
    the sandbox floor is 3.9, so such names have no portable
    invocation. Fail closed with a clear message instead of installing
    an unreachable command.
    """
    with pytest.raises(ValueError, match="leading dash"):
        ToolCommand([_named_tool("-find")])


# --- round 4: examples are validated; invalid ones marked illustrative -------


def test_example_instance_honors_ceil_and_maxlength() -> None:
    """An integer minimum of 1.5 must round up; maxLength must bound strings."""
    from inspect_ai.agent._human.commands.tool import _example_instance

    assert _example_instance({"type": "integer", "minimum": 1.5}) >= 1.5
    assert len(_example_instance({"type": "string", "maxLength": 2})) <= 2


def _one_param_tool(schema: JSONSchema):
    from typing import Any

    from inspect_ai.tool import ToolParams

    async def execute(**kwargs: Any) -> str:
        """Accept anything.

        Returns:
            A marker.
        """
        return "ok"

    return ToolDef(
        execute,
        name="one_param",
        description="Accept anything.",
        parameters=ToolParams(properties={"config": schema}, required=["config"]),
    ).as_tool()


def test_valid_example_advertised_as_such() -> None:
    from inspect_ai.util import JSONSchema

    schema = JSONSchema(
        type="object",
        properties={"a": JSONSchema(type="string")},
        required=["a"],
        description="Config.",
    )
    code = ToolCommand([_one_param_tool(schema)]).get_cli_parser_code()
    line = next(ln for ln in code.splitlines() if "dest='arg_config'" in ln)
    assert "e.g." in line
    assert "illustrative" not in line


def test_unsatisfiable_example_marked_illustrative() -> None:
    """When no valid instance can be generated, don't claim copy-pasteability.

    Defaults and examples are annotations, not guaranteed-valid
    instances, and generators can't honor every constraint (pattern,
    etc.) — validate the candidate and mark failures as illustrative.
    """
    from inspect_ai.util import JSONSchema

    schema = JSONSchema(
        type="object",
        properties={"a": JSONSchema(type="string", pattern="^Z{5}$")},
        required=["a"],
        description="Config.",
    )
    code = ToolCommand([_one_param_tool(schema)]).get_cli_parser_code()
    line = next(ln for ln in code.splitlines() if "dest='arg_config'" in ln)
    assert "illustrative" in line
    assert "e.g." not in line


# --- round 3: ToolError surfaces cleanly, like unexpected exceptions ---------


@pytest.mark.anyio
async def test_tool_error_surfaces_without_raising() -> None:
    """An expected ToolError returns a clean message, not an RPC traceback.

    Re-raising sends it through the sandbox-service boundary, which
    hands the human a traceback for what is an ordinary, expected tool
    failure (the outcome a model receives as a plain error message).
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.tool import ToolError

    async def execute() -> str:
        """Fail in the expected way.

        Returns:
            Never returns.
        """
        raise ToolError("no such incident")

    failing = ToolDef(
        execute, name="failing", description="Fail expectedly.", parameters={}
    ).as_tool()

    handler = ToolCommand([failing]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="failing", arguments={})

    assert "no such incident" in str(result)
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None
    assert events[0].failed is None  # expected failure, not a hard error


# --- round 3: help examples honor constraints, defaults, and examples --------


def test_example_instance_honors_constraints_and_defaults() -> None:
    """Generated examples must satisfy the schema constraints they illustrate.

    A minLength=10 string rendered as "text" and a minimum=5 integer as 1
    produce examples validate_tool_input() immediately rejects.
    """
    from inspect_ai.agent._human.commands.tool import _example_instance

    schema = {
        "type": "object",
        "properties": {
            "long": {"type": "string", "minLength": 10},
            "count": {"type": "integer", "minimum": 5},
            "rate": {"type": "number", "exclusiveMinimum": 2.0},
            "named": {"type": "string", "default": "from-default"},
            "shown": {"type": "integer", "examples": [42]},
        },
        "required": ["long", "count", "rate", "named", "shown"],
    }
    example = _example_instance(schema)
    assert len(example["long"]) >= 10
    assert example["count"] >= 5
    assert example["rate"] > 2.0
    assert example["named"] == "from-default"
    assert example["shown"] == 42


# --- round 3: only advertise null where it is actually accepted --------------


@tool
def _nullable_menagerie():
    async def execute(
        value: int | None = None,
        tags: list[str] | None = None,
        strict: bool | None = None,
    ) -> str:
        """Exercise nullable parameter varieties.

        Args:
            value: A nullable integer.
            tags: A nullable array.
            strict: A nullable boolean.

        Returns:
            A marker.
        """
        return "ok"

    return execute


def test_every_nullable_param_gets_a_null_flag() -> None:
    """Every nullable parameter — scalar, array, boolean — gets --null-<name>.

    The dedicated flag gives one uniform null spelling, including for
    booleans (which have no token-based spelling at all).
    """
    code = ToolCommand([_nullable_menagerie()]).get_cli_parser_code()
    for name in ("value", "tags", "strict"):
        assert f"'--null-{name}'" in code
    assert "_nullable(" not in code  # token-converter magic is gone


# --- round 3: nullability and requiredness are independent --------------------


def _required_nullable_tool():
    from typing import Any

    from inspect_ai.tool import ToolParams
    from inspect_ai.util import JSONSchema

    async def execute(**kwargs: Any) -> str:
        """Accept a required-but-nullable value.

        Returns:
            A rendering of the value.
        """
        return repr(kwargs["value"])

    return ToolDef(
        execute,
        name="req_nullable",
        description="Accept a required-but-nullable value.",
        parameters=ToolParams(
            properties={
                "value": JSONSchema(
                    anyOf=[JSONSchema(type="integer"), JSONSchema(type="null")],
                    description="Required, may be null.",
                )
            },
            required=["value"],
        ),
    ).as_tool()


def test_required_nullable_flag_is_required() -> None:
    """A required int|None parameter must not be omittable.

    Nullability made the flag optional (SUPPRESS), so argparse accepted
    omission and only the eval-side validator rejected it — a worse
    error, later. null is an accepted *value*; the flag stays required.
    """
    parser, _ = _build_parsers([_required_nullable_tool()])
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["tool", "req_nullable"])
    assert exc_info.value.code == 2


def test_required_nullable_accepts_null_value() -> None:
    parser, _ = _build_parsers([_required_nullable_tool()])
    kwargs = _handler_kwargs(parser, ["tool", "req_nullable", "--null-value"])
    assert kwargs == {"value": None}


# --- round 3: arbitrary schema property names are escaped, not rejected -----


def _kwargs_tool(prop: str):
    """A **kwargs tool whose declared schema has an arbitrary property name."""
    from typing import Any

    from inspect_ai.tool import ToolParams
    from inspect_ai.util import JSONSchema

    async def execute(**kwargs: Any) -> str:
        """Echo the hostile property.

        Returns:
            The value.
        """
        return str(kwargs[prop])

    return ToolDef(
        execute,
        name="hostile_params",
        description="Echo the hostile property.",
        parameters=ToolParams(
            properties={prop: JSONSchema(type="string", description="Hostile.")}
        ),
    ).as_tool()


def test_quoted_property_name_generates_working_cli() -> None:
    """Property names are escaped into generated source, not interpolated.

    ToolParams permits arbitrary JSON property names and tool_params()
    passes them through to **kwargs tools, so models can use such tools;
    a name containing a quote must not brick (or inject into) the
    generated CLI, and must remain invocable by the human.
    """
    prop = 'value"'
    parser, _ = _build_parsers([_kwargs_tool(prop)])
    kwargs = _handler_kwargs(parser, ["tool", "hostile_params", '--value"', "abc"])
    assert kwargs == {prop: "abc"}


def test_injection_shaped_property_name_is_inert() -> None:
    """A code-injection-shaped name becomes an inert quoted literal."""
    prop = 'x", exec("raise SystemExit"), "'
    parser, _ = _build_parsers([_kwargs_tool(prop)])  # would raise if executed
    kwargs = _handler_kwargs(parser, ["tool", "hostile_params", f"--{prop}", "v"])
    assert kwargs == {prop: "v"}


@pytest.mark.anyio
async def test_arbitrary_property_name_service_roundtrip() -> None:
    """The service executes **kwargs tools with arbitrary property names."""
    from inspect_ai.log._transcript import Transcript, init_transcript

    prop = "a b"
    handler = ToolCommand([_kwargs_tool(prop)]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="hostile_params", arguments={prop: "ok"})
    assert result == "ok"


def test_empty_property_name_rejected() -> None:
    """An empty property name has no possible flag spelling — fail closed."""
    with pytest.raises(ValueError, match="empty"):
        ToolCommand([_kwargs_tool("")])


# --- finding 5: every non-text standalone content uses the omission marker ---


def test_standalone_document_not_dumped_to_terminal() -> None:
    """A standalone ContentDocument must not print its base64 data URI."""
    from inspect_ai._util.content import ContentDocument

    out = tool_result_to_str(
        ContentDocument(document="data:application/pdf;base64,JVBERi0xLjQK")
    )
    assert "omitted" in out
    assert "base64" not in out


# --- finding 4: parameters that would break the generated CLI fail closed ----


def test_param_named_help_rejected_at_construction() -> None:
    """A parameter named `help` would brick the whole generated CLI.

    add_argument("--help") collides with argparse's automatic flag and
    raises at parser construction — taking down every command including
    `task submit`. Reject it host-side, before install.
    """

    async def execute(help: str) -> str:
        """Echo help.

        Args:
            help: A parameter named help.

        Returns:
            The value.
        """
        return help

    bad = ToolDef(
        execute,
        name="helper",
        description="Echo help.",
        parameters={"help": "A parameter named help."},
    ).as_tool()

    with pytest.raises(ValueError, match="help"):
        ToolCommand([bad])


def test_boolean_negative_alias_collision_rejected() -> None:
    """A bool `x` generates --no-x, colliding with a param named `no_x`."""

    async def execute(dry_run: bool = False, no_dry_run: str = "") -> str:
        """Collide a boolean's negative alias.

        Args:
            dry_run: A boolean (generates --dry-run/--no-dry-run).
            no_dry_run: A parameter whose flag is also --no-dry-run.

        Returns:
            A marker.
        """
        return "ok"

    bad = ToolDef(
        execute,
        name="collider",
        description="Collide a boolean's negative alias.",
        parameters={
            "dry_run": "A boolean.",
            "no_dry_run": "Collides with the boolean's negative alias.",
        },
    ).as_tool()

    with pytest.raises(ValueError, match="no-dry-run"):
        ToolCommand([bad])


def test_plain_boolean_param_still_accepted() -> None:
    """Control: an ordinary boolean parameter constructs fine."""
    ToolCommand([_format_text()])


# --- finding 1: human calls must honor the declared JSON Schema --------------


@pytest.mark.anyio
async def test_schema_constraints_enforced_for_human_calls() -> None:
    """Human calls validate against the declared schema like model calls do.

    A ToolDef(parameters=...) over **kwargs has no typed signature for
    tool_params() to convert against, so schema constraints (minimum,
    enum, required) were only enforced on the model path — the human
    could execute calls a model would have had rejected.
    """
    from typing import Any

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.tool import ToolParams
    from inspect_ai.util import JSONSchema

    executed: dict = {}

    async def execute(**kwargs: Any) -> str:
        """Set the level.

        Returns:
            Confirmation.
        """
        executed["level"] = kwargs.get("level")
        return "set"

    leveled = ToolDef(
        execute,
        name="set_level",
        description="Set the level.",
        parameters=ToolParams(
            properties={
                "level": JSONSchema(type="integer", minimum=1, description="The level.")
            },
            required=["level"],
        ),
    ).as_tool()

    handler = ToolCommand([leveled]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="set_level", arguments={"level": 0})

    assert executed == {}  # the tool must not run
    assert "validation" in str(result).lower()
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None and events[0].error.type == "parsing"

    # and a conforming call goes through
    result = await handler(tool="set_level", arguments={"level": 2})
    assert result == "set"
    assert executed == {"level": 2}


# --- finding 2: a ToolEvent must be recorded on every outcome ----------------


@pytest.mark.anyio
async def test_unexpected_exception_records_failed_event_and_fails() -> None:
    """A tool raising a non-ToolError records a failed event, then fails the sample.

    The model path raises unexpected tool exceptions out of execute_tools();
    the human path must give the same disposition. The human gets a reply
    (rather than a raw RPC error) and the failure is held for the human
    agent service, which ends the sample with it (see
    test_human_service_raises_unexpected_tool_exception).
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> str:
        """Raise an ordinary exception.

        Returns:
            Never returns.
        """
        raise RuntimeError("boom")

    broken = ToolDef(
        execute,
        name="broken",
        description="Raise an ordinary exception.",
        parameters={},
    ).as_tool()

    command = ToolCommand([broken])
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="broken", arguments={})

    assert "Error executing tool 'broken'" in str(result)
    assert "boom" in str(result)
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None
    assert "boom" in events[0].error.message
    assert events[0].failed is True
    assert isinstance(command.failure, RuntimeError)
    assert str(command.failure) == "boom"


@pytest.mark.anyio
async def test_finalized_event_leaves_pending_registry() -> None:
    """Finalization must publish the update, not just mutate the event.

    _set_result() without transcript()._event_updated() leaves the
    completed event registered pending: live subscribers never see the
    completion and bounded transcripts pin the event forever.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_addition()]).service(state=_agent_state())
    init_transcript(Transcript())
    await handler(tool="_addition", arguments={"x": 1, "y": 2})

    assert [e for e in transcript().pending_events if e.event == "tool"] == []


@pytest.mark.anyio
async def test_typed_param_records_raw_arguments() -> None:
    """Events must record the JSON arguments as sent, not converted values.

    tool_params() converts an ISO string to datetime; recording the
    converted value made ToolEvent creation fail *after* the tool had
    already executed (side effects done, nothing recorded).
    """
    from datetime import datetime

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute(when: datetime) -> str:
        """Format a timestamp.

        Args:
            when: The timestamp.

        Returns:
            The year.
        """
        return str(when.year)

    dated = ToolDef(
        execute,
        name="dated",
        description="Format a timestamp.",
        parameters={"when": "The timestamp."},
    ).as_tool()

    handler = ToolCommand([dated]).service(state=_agent_state())
    init_transcript(Transcript())
    result = await handler(tool="dated", arguments={"when": "2026-01-02T03:04:05"})
    assert result == "2026"

    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].arguments == {"when": "2026-01-02T03:04:05"}
    assert events[0].result == "2026"


@pytest.mark.anyio
async def test_event_is_pending_during_execution() -> None:
    """The event is recorded before execution, then finalized.

    A pending-first event survives even if the tool (or Inspect) dies
    mid-call, matching how model tool calls are recorded.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    seen: dict = {}

    async def execute() -> str:
        """Observe the transcript mid-execution.

        Returns:
            A marker.
        """
        pending = [e for e in transcript().events if e.event == "tool"]
        seen["count"] = len(pending)
        seen["pending"] = pending[0].pending if pending else None
        return "done"

    observer = ToolDef(
        execute,
        name="observer",
        description="Observe the transcript mid-execution.",
        parameters={},
    ).as_tool()

    handler = ToolCommand([observer]).service(state=_agent_state())
    init_transcript(Transcript())
    await handler(tool="observer", arguments={})

    assert seen["count"] == 1
    assert seen["pending"] is True
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].pending is None  # finalized
    assert events[0].completed is not None


# --- review round 2026-10: failure policy, cancellation, no_ booleans, ------
# --- wrapped termination, per-tool max_output --------------------------------


def _sleeper_tool(name: str, started, parallel: bool = True):
    import anyio

    async def execute() -> str:
        """Sleep until cancelled.

        Returns:
            Never returns.
        """
        started.set()
        await anyio.sleep(30)
        return "unreachable"

    return ToolDef(
        execute,
        name=name,
        description="Sleep.",
        parameters={},
        parallel=parallel,
    ).as_tool()


async def _run_human_service_with(monkeypatch, commands, calls) -> None:
    """Run run_human_agent_service() over a fake sandbox service.

    The fake makes `calls` (tool name, arguments) through the "tool" service
    method, then polls until() the way sandbox_service() does, failing if the
    service would keep running.
    """
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._human import service as human_service
    from inspect_ai.log._transcript import Transcript, init_transcript

    async def fake_sandbox_service(name, methods, until, sandbox, user) -> None:
        for tool_name, arguments in calls:
            await methods["tool"](tool=tool_name, arguments=arguments)
        if not until():
            raise AssertionError("human agent service kept running")

    monkeypatch.setattr(human_service, "sandbox_service", fake_sandbox_service)
    monkeypatch.setattr(human_service, "sandbox", lambda: None)
    init_transcript(Transcript())
    await human_service.run_human_agent_service(
        None, AgentState(messages=[]), commands, None
    )


@pytest.mark.anyio
async def test_human_service_raises_unexpected_tool_exception(monkeypatch) -> None:
    """An unexpected tool exception ends the human agent with that exception.

    Service methods run inside the sandbox service, which turns exceptions
    into RPC errors and keeps polling, so the failure has to be raised by
    run_human_agent_service() for the sample's error handling to see it.
    """
    command = ToolCommand(
        [_raising_tool("raiser", lambda: RuntimeError("unexpected defect"))]
    )
    with pytest.raises(RuntimeError, match="unexpected defect"):
        await _run_human_service_with(monkeypatch, [command], [("raiser", {})])


@pytest.mark.anyio
async def test_human_service_continues_after_expected_tool_error(
    monkeypatch,
) -> None:
    """A ToolError stays recoverable: the service keeps running."""
    command = ToolCommand([_raising_tool("raiser", lambda: ToolError("try again"))])
    with pytest.raises(AssertionError, match="kept running"):
        await _run_human_service_with(monkeypatch, [command], [("raiser", {})])
    assert command.failure is None


@pytest.mark.anyio
async def test_operator_cancel_stops_hanging_tool_call(monkeypatch) -> None:
    """cancel-tool-call stops a hanging human tool call and frees its slot.

    The pending event must carry a cancel hook (the control resolver rejects
    events without one), the call must finish as the operator-cancel timeout
    the model path records, and a serial call must release the scheduler so
    the next call runs.
    """
    from types import SimpleNamespace

    import anyio

    from inspect_ai._control import cancel as control_cancel
    from inspect_ai._control import state as control_state
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    started = anyio.Event()
    handler = ToolCommand(
        [_sleeper_tool("sleeper", started, parallel=False), _addition()]
    ).service(state=_agent_state())
    init_transcript(Transcript())

    sample = SimpleNamespace(
        completed=None, transcript=transcript(), sample=SimpleNamespace(id=1), epoch=1
    )
    monkeypatch.setattr(
        control_state, "find_active_sample", lambda *args, **kwargs: sample
    )

    results: dict = {}

    async def call() -> None:
        results["sleeper"] = await handler(tool="sleeper", arguments={})

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call)
            await started.wait()
            response = await control_cancel.cancel_tool_call("eval", "1", 1)
            assert response is not None
            assert response.get("ok") is True, response
            assert response.get("changed") is True, response

        # the serial slot was released: the next call runs
        assert await handler(tool="_addition", arguments={"x": 1, "y": 2}) == "3"

    assert "timed out" in results["sleeper"]
    event = next(
        e for e in transcript().events if e.event == "tool" and e.function == "sleeper"
    )
    assert event.pending is None
    assert event.cancelled
    assert event.error is not None and event.error.type == "timeout"
    assert event.failed is None


@pytest.mark.anyio
async def test_tui_cancel_stops_hanging_tool_call() -> None:
    """The TUI timeout control calls ToolEvent._cancel() directly."""
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    started = anyio.Event()
    handler = ToolCommand([_sleeper_tool("sleeper", started)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())

    results: dict = {}

    async def call() -> None:
        results["sleeper"] = await handler(tool="sleeper", arguments={})

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call)
            await started.wait()
            event = next(e for e in transcript().events if e.event == "tool")
            event._cancel()

    assert "timed out" in results["sleeper"]
    assert event.pending is None
    assert event.error is not None and event.error.type == "timeout"


def _no_cache_tool():
    async def execute(no_cache: bool = False) -> str:
        """Report the flag.

        Args:
            no_cache: Skip the cache.

        Returns:
            The value received.
        """
        return str(no_cache)

    return ToolDef(
        execute,
        name="fetch",
        description="Report the flag.",
        parameters={"no_cache": "Skip the cache."},
    ).as_tool()


def test_boolean_param_named_no_x_has_true_and_false_flags() -> None:
    """`no_cache: bool` needs a flag that sends True and one that sends False.

    BooleanOptionalAction infers False from any option starting --no-, so
    --no-cache and --no-no-cache both sent False (and Python 3.14 refuses
    to build such an option at all, taking down the whole generated CLI).
    """
    parser, _ = _build_parsers([_no_cache_tool()])
    assert _handler_kwargs(parser, ["tool", "fetch", "--no-cache"]) == {
        "no_cache": True
    }
    assert _handler_kwargs(parser, ["tool", "fetch", "--no-no-cache"]) == {
        "no_cache": False
    }
    assert _handler_kwargs(parser, ["tool", "fetch"]) == {}


def test_boolean_cli_does_not_use_boolean_optional_action() -> None:
    """Generated code must not depend on BooleanOptionalAction.

    Its --no- prefix inference is the ambiguity above, and on Python 3.14 it
    raises ValueError at parser construction for an option starting --no-.
    """
    code = ToolCommand([_no_cache_tool(), _format_text()]).get_cli_parser_code()
    assert "BooleanOptionalAction" not in code


def test_boolean_true_false_flags_are_mutually_exclusive() -> None:
    parser, _ = _build_parsers([_format_text()])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["tool", "_format_text", "--text", "hi", "--reverse", "--no-reverse"]
        )


def test_nullable_boolean_has_true_false_and_null_flags() -> None:
    async def execute(flag: bool | None = None) -> str:
        """Report the flag.

        Args:
            flag: A nullable boolean.

        Returns:
            The value received.
        """
        return str(flag)

    nullable = ToolDef(
        execute,
        name="nullable",
        description="Report the flag.",
        parameters={"flag": "A nullable boolean."},
    ).as_tool()
    parser, _ = _build_parsers([nullable])
    assert _handler_kwargs(parser, ["tool", "nullable", "--flag"]) == {"flag": True}
    assert _handler_kwargs(parser, ["tool", "nullable", "--no-flag"]) == {"flag": False}
    assert _handler_kwargs(parser, ["tool", "nullable", "--null-flag"]) == {
        "flag": None
    }
    with pytest.raises(SystemExit):
        parser.parse_args(["tool", "nullable", "--flag", "--null-flag"])


def test_required_boolean_requires_one_of_its_flags() -> None:
    async def execute(confirm: bool) -> str:
        """Report the flag.

        Args:
            confirm: A required boolean.

        Returns:
            The value received.
        """
        return str(confirm)

    required = ToolDef(
        execute,
        name="required",
        description="Report the flag.",
        parameters={"confirm": "A required boolean."},
    ).as_tool()
    parser, _ = _build_parsers([required])
    with pytest.raises(SystemExit):
        parser.parse_args(["tool", "required"])
    assert _handler_kwargs(parser, ["tool", "required", "--no-confirm"]) == {
        "confirm": False
    }


def _wrapped_termination_tool(shape: str):
    import anyio

    from inspect_ai._util.exception import TerminateSampleError

    async def execute() -> str:
        """Raise a termination wrapped in an expected tool error.

        Returns:
            Never returns.
        """
        if shape == "cause":
            try:
                raise TerminateSampleError("must stop")
            except TerminateSampleError as ex:
                raise ToolError("outer expected failure") from ex
        elif shape == "group":

            async def terminate() -> None:
                raise TerminateSampleError("must stop")

            async def tool_error() -> None:
                raise ToolError("outer expected failure")

            async with anyio.create_task_group() as tg:
                tg.start_soon(tool_error)
                tg.start_soon(terminate)
        return "unreachable"

    return ToolDef(
        execute, name="wrapper", description="Wrap a termination.", parameters={}
    ).as_tool()


@pytest.mark.anyio
@pytest.mark.parametrize("shape", ["cause", "group"])
async def test_wrapped_termination_ends_sample_through_dispatcher(
    shape, monkeypatch
) -> None:
    """A TerminateSampleError wrapped by a ToolError (or grouped) still terminates.

    The dispatcher treats termination as sticky across the exception's
    causal history; reducing the exception to one expected ToolError
    before checking for termination consumed it.
    """
    from test_helpers.service_dispatch import (
        REQUEST_FILE,
        REQUEST_ID,
        dispatching_service,
    )

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_wrapped_termination_tool(shape)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())
    errors: list[str | None] = []
    service = dispatching_service(
        monkeypatch, "tool", handler, {"tool": "wrapper", "arguments": {}}, errors
    )
    with pytest.raises(TerminateSampleError, match="must stop"):
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)

    assert len(errors) == 1
    assert errors[0] is not None and "must stop" in errors[0]
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.pending is None


def _sized_tool(name: str, result, max_output: int | None = None):
    async def execute() -> object:
        """Return a fixed result.

        Returns:
            The result.
        """
        return result

    return ToolDef(
        execute,
        name=name,
        description="Return a fixed result.",
        parameters={},
        max_output=max_output,
    ).as_tool()


@pytest.mark.anyio
async def test_tool_max_output_caps_human_result() -> None:
    """A tool's own max_output applies to human calls as it does to model calls."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_sized_tool("small", "x" * 80, max_output=8)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())
    result = str(await handler(tool="small", arguments={}))

    assert "x" * 80 not in result
    assert "truncated" in result
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.truncated == (80, 8)


@pytest.mark.anyio
async def test_tool_max_output_raises_human_limit() -> None:
    """A tool allowed more than the default limit is not cut to the default."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    big = "x" * (32 * 1024)
    handler = ToolCommand([_sized_tool("big", big, max_output=64 * 1024)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())
    result = await handler(tool="big", arguments={})

    assert result == big
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.truncated is None


@pytest.mark.anyio
async def test_tool_max_output_caps_expected_error_partial() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.util import OutputLimitExceededError

    async def execute() -> str:
        """Hit an output limit with a partial result.

        Returns:
            Never returns.
        """
        raise OutputLimitExceededError("1 MiB", "y" * 80)

    limited = ToolDef(
        execute,
        name="limited",
        description="Hit an output limit.",
        parameters={},
        max_output=8,
    ).as_tool()
    handler = ToolCommand([limited]).service(state=_agent_state())
    init_transcript(Transcript())
    result = str(await handler(tool="limited", arguments={}))

    assert "y" * 80 not in result
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.truncated == (80, 8)


@pytest.mark.anyio
async def test_tool_max_output_caps_structured_terminal_rendering() -> None:
    """Structured content is kept in the event; its terminal text uses the tool limit."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    content = [ContentText(text="z" * 80), ContentImage(image="data:image/png;base64,")]
    handler = ToolCommand([_sized_tool("mixed", content, max_output=8)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())
    result = str(await handler(tool="mixed", arguments={}))

    assert "z" * 80 not in result
    assert "truncated" in result
    event = next(e for e in transcript().events if e.event == "tool")
    assert isinstance(event.result, list)
    assert isinstance(event.result[0], ContentText)
    assert event.result[0].text == "z" * 80


# --- review pass 1 (2026-10-15): termination during argument construction, --
# --- percent signs in synthesized help ---------------------------------------


_CONSTRUCTION_SHAPE: dict[str, str] = {}


@dataclass
class _ConstructedArgument:
    """A typed argument whose construction raises (see _CONSTRUCTION_SHAPE)."""

    value: int

    def __post_init__(self) -> None:
        from inspect_ai._util.exception import TerminateSampleError
        from inspect_ai.util._limit import LimitExceededError

        shape = _CONSTRUCTION_SHAPE["shape"]
        if shape == "runtime":
            raise RuntimeError("constructor defect")
        elif shape == "limit":
            raise LimitExceededError("token", value=1001, limit=1000)
        elif shape == "tool_error":
            raise ToolError("value must be positive")
        elif shape == "direct":
            raise TerminateSampleError("must stop")
        elif shape == "cause":
            try:
                raise TerminateSampleError("must stop")
            except TerminateSampleError as ex:
                raise ToolError("wrapped validator failure") from ex
        else:
            raise ExceptionGroup(
                "validator errors",
                [ToolError("retry"), TerminateSampleError("must stop")],
            )


@pytest.mark.anyio
@pytest.mark.parametrize("shape", ["direct", "cause", "group"])
async def test_termination_during_argument_construction_ends_sample(
    shape, monkeypatch
) -> None:
    """A termination raised while building a typed argument still ends the sample.

    tool_params() runs dataclass/Pydantic constructors and validators, which
    are user code; treating every exception there as a parsing error answered
    the RPC normally and the termination never reached the dispatcher.
    """
    from test_helpers.service_dispatch import (
        REQUEST_FILE,
        REQUEST_ID,
        dispatching_service,
    )

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute(argument: _ConstructedArgument) -> str:
        """Take a typed argument.

        Args:
            argument: An argument whose construction terminates the sample.

        Returns:
            Never returns.
        """
        return "body must not run"

    typed = ToolDef(
        execute,
        name="typed",
        description="Take a typed argument.",
        parameters={"argument": "An argument."},
    ).as_tool()

    monkeypatch.setitem(_CONSTRUCTION_SHAPE, "shape", shape)
    command = ToolCommand([typed])
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    errors: list[str | None] = []
    service = dispatching_service(
        monkeypatch,
        "tool",
        handler,
        {"tool": "typed", "arguments": {"argument": {"value": 1}}},
        errors,
    )
    with pytest.raises(TerminateSampleError, match="must stop"):
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)

    assert len(errors) == 1
    assert errors[0] is not None and "must stop" in errors[0]
    assert command.failure is None
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.pending is None


def _percent_kwargs_tool():
    """A **kwargs tool with a boolean and a nullable property whose names hold %."""
    from typing import Any

    from inspect_ai.tool import ToolParams
    from inspect_ai.util import JSONSchema

    async def execute(**kwargs: Any) -> str:
        """Echo the arguments.

        Returns:
            The arguments.
        """
        return str(kwargs)

    return ToolDef(
        execute,
        name="percent_names",
        description="Echo the arguments.",
        parameters=ToolParams(
            properties={
                "%": JSONSchema(type="boolean", description="A flag."),
                "50%": JSONSchema(
                    anyOf=[JSONSchema(type="string"), JSONSchema(type="null")],
                    description="A nullable value.",
                ),
            },
            required=["%"],
        ),
    ).as_tool()


def test_percent_in_property_names_survives_help_rendering() -> None:
    """Synthesized help ('send false for <name>') must escape % too.

    argparse percent-interpolates help at render time, so a property name
    holding % made `task tool <name> --help` raise ValueError.
    """
    parser, namespace = _build_parsers([_percent_kwargs_tool()])
    help_text = namespace["parser_0"].format_help()
    assert "send false for %" in help_text
    assert "send null for 50%" in help_text
    assert _handler_kwargs(parser, ["tool", "percent_names", "--%"]) == {"%": True}


def test_unrenderable_help_rejected_at_construction(monkeypatch) -> None:
    """Construction renders each tool's help, so a help failure fails closed."""
    from inspect_ai.agent._human.commands import tool as tool_module

    monkeypatch.setattr(tool_module, "_help", lambda text: text)
    with pytest.raises(ValueError, match="percent_names"):
        ToolCommand([_percent_kwargs_tool()])


# --- review pass 2 (2026-10-15): constructor failures, mixed exception -------
# --- groups, capped error replies ----------------------------------------------


def _typed_tool():
    async def execute(argument: _ConstructedArgument) -> str:
        """Take a typed argument.

        Args:
            argument: An argument whose construction raises.

        Returns:
            Never returns.
        """
        return "body must not run"

    return ToolDef(
        execute,
        name="typed",
        description="Take a typed argument.",
        parameters={"argument": "An argument."},
    ).as_tool()


async def _dispatch(monkeypatch, command: ToolCommand, tool: str, arguments: dict):
    """Serve one `tool` request through the real sandbox service dispatcher.

    Returns the RPC error (None when the method returned) and the mock
    active sample that the dispatcher routes limits to.
    """
    from unittest.mock import MagicMock, patch

    from test_helpers.service_dispatch import (
        REQUEST_FILE,
        REQUEST_ID,
        dispatching_service,
    )

    from inspect_ai.log._transcript import Transcript, init_transcript

    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    errors: list[str | None] = []
    service = dispatching_service(
        monkeypatch, "tool", handler, {"tool": tool, "arguments": arguments}, errors
    )
    active = MagicMock()
    with patch("inspect_ai.log._samples.sample_active", return_value=active):
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
    assert len(errors) == 1
    return errors[0], active


@pytest.mark.anyio
async def test_constructor_defect_fails_sample(monkeypatch) -> None:
    """An unexpected exception from a typed argument's constructor fails the sample.

    tool_params() runs constructors and validators (user code); on the model
    path that is inside the execution exception boundary, so a defect there
    gets the same disposition as one in the tool body.
    """
    from inspect_ai.log._transcript import transcript

    monkeypatch.setitem(_CONSTRUCTION_SHAPE, "shape", "runtime")
    command = ToolCommand([_typed_tool()])
    error, active = await _dispatch(
        monkeypatch, command, "typed", {"argument": {"value": 1}}
    )
    assert error is None  # the human gets a reply
    assert isinstance(command.failure, RuntimeError)
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.failed is True


@pytest.mark.anyio
async def test_constructor_limit_reaches_sample(monkeypatch) -> None:
    from inspect_ai.log._transcript import transcript

    monkeypatch.setitem(_CONSTRUCTION_SHAPE, "shape", "limit")
    command = ToolCommand([_typed_tool()])
    error, active = await _dispatch(
        monkeypatch, command, "typed", {"argument": {"value": 1}}
    )
    assert error is not None and "Limit exceeded" in error
    assert active.limit_exceeded.call_count == 1
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.error is not None and event.error.type == "limit"


@pytest.mark.anyio
async def test_constructor_tool_error_stays_recoverable(monkeypatch) -> None:
    """Control: an argument rejected with a ToolError is a recoverable reply."""
    monkeypatch.setitem(_CONSTRUCTION_SHAPE, "shape", "tool_error")
    command = ToolCommand([_typed_tool()])
    error, active = await _dispatch(
        monkeypatch, command, "typed", {"argument": {"value": 1}}
    )
    assert error is None
    assert command.failure is None
    assert active.limit_exceeded.call_count == 0


_GROUP_REPEATS = 50


def _group_tool(exceptions):
    async def execute() -> str:
        """Raise an exception group.

        Returns:
            Never returns.
        """
        raise ExceptionGroup("tool errors", exceptions())

    return ToolDef(
        execute, name="grouped", description="Raise a group.", parameters={}
    ).as_tool()


@pytest.mark.anyio
@pytest.mark.parametrize("fatal_first", [False, True])
async def test_group_with_fatal_leaf_fails_sample(monkeypatch, fatal_first) -> None:
    """A fatal leaf beside a recoverable one fails the sample, in either order.

    Repeated with fresh exceptions: reducing a group to one leaf picked in
    set (address) order chose the recoverable leaf only some of the time.
    """
    from inspect_ai.log._transcript import transcript

    def exceptions() -> list[Exception]:
        leaves: list[Exception] = [ToolError("retry"), RuntimeError("fatal defect")]
        return leaves[::-1] if fatal_first else leaves

    for _ in range(_GROUP_REPEATS):
        command = ToolCommand([_group_tool(exceptions)])
        error, active = await _dispatch(monkeypatch, command, "grouped", {})
        assert error is None
        assert isinstance(command.failure, RuntimeError)
        assert str(command.failure) == "fatal defect"
        event = next(e for e in transcript().events if e.event == "tool")
        assert event.failed is True


@pytest.mark.anyio
@pytest.mark.parametrize("limit_first", [False, True])
async def test_group_with_limit_leaf_reaches_sample(monkeypatch, limit_first) -> None:
    from inspect_ai.util._limit import LimitExceededError

    def exceptions() -> list[Exception]:
        leaves: list[Exception] = [
            ToolError("retry"),
            LimitExceededError("token", value=1001, limit=1000),
        ]
        return leaves[::-1] if limit_first else leaves

    for _ in range(_GROUP_REPEATS):
        command = ToolCommand([_group_tool(exceptions)])
        error, active = await _dispatch(monkeypatch, command, "grouped", {})
        assert error is not None and "Limit exceeded" in error
        assert active.limit_exceeded.call_count == 1
        assert command.failure is None


@pytest.mark.anyio
async def test_group_of_recoverable_errors_stays_recoverable(monkeypatch) -> None:
    """Control: a group of expected errors is one recoverable reply."""
    from inspect_ai.log._transcript import transcript

    command = ToolCommand(
        [_group_tool(lambda: [ToolError("first"), ToolError("second")])]
    )
    error, active = await _dispatch(monkeypatch, command, "grouped", {})
    assert error is None
    assert command.failure is None
    assert active.limit_exceeded.call_count == 0
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.failed is None
    assert event.error is not None and event.error.message == "first"


@pytest.mark.anyio
async def test_large_expected_error_reply_is_capped() -> None:
    """The terminal reply for an expected error honors the tool's max_output."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> str:
        """Raise a huge ToolError.

        Returns:
            Never returns.
        """
        raise ToolError("x" * 1_000_000)

    loud = ToolDef(
        execute, name="loud", description="Raise.", parameters={}, max_output=8
    ).as_tool()
    handler = ToolCommand([loud]).service(state=_agent_state())
    init_transcript(Transcript())
    result = str(await handler(tool="loud", arguments={}))

    assert len(result) < 1000
    assert "truncated" in result
    event = next(e for e in transcript().events if e.event == "tool")
    assert event.error is not None and event.error.type == "unknown"


@pytest.mark.anyio
async def test_large_unexpected_error_reply_is_capped() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript

    async def execute() -> str:
        """Raise a huge RuntimeError.

        Returns:
            Never returns.
        """
        raise RuntimeError("x" * 1_000_000)

    loud = ToolDef(
        execute, name="loud", description="Raise.", parameters={}, max_output=8
    ).as_tool()
    command = ToolCommand([loud])
    handler = command.service(state=_agent_state())
    init_transcript(Transcript())
    result = str(await handler(tool="loud", arguments={}))

    assert len(result) < 1000
    assert command.failure is not None


@pytest.mark.anyio
async def test_input_derived_validation_reply_is_capped() -> None:
    """Schema-validation messages echo the human's input; the reply is capped."""
    from inspect_ai.log._transcript import Transcript, init_transcript

    async def execute(count: int) -> str:
        """Take a count.

        Args:
            count: A count.

        Returns:
            The count.
        """
        return str(count)

    counter = ToolDef(
        execute,
        name="counter",
        description="Take a count.",
        parameters={"count": "A count."},
        max_output=8,
    ).as_tool()
    handler = ToolCommand([counter]).service(state=_agent_state())
    init_transcript(Transcript())
    result = str(await handler(tool="counter", arguments={"count": "y" * 1_000_000}))

    assert len(result) < 1000
    assert "truncated" in result


# --- review pass 3 (2026-10-15): overlapping cancellation, bounded terminal --
# --- rendering -----------------------------------------------------------------


@pytest.mark.anyio
async def test_operator_and_parent_cancel_together_finalize_event() -> None:
    """An operator cancel and a parent cancel in the same turn still finalize.

    The call's own scope doesn't absorb the cancellation when an enclosing
    scope is cancelled too, so the cancellation escapes past the operator-
    cancel finalizer; the event must not stay pending.
    """
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    started = anyio.Event()
    handler = ToolCommand([_sleeper_tool("sleeper", started)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())

    async def call() -> None:
        await handler(tool="sleeper", arguments={})

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call)
            await started.wait()
            event = next(e for e in transcript().events if e.event == "tool")
            event._cancel()
            tg.cancel_scope.cancel()

    assert event.pending is None
    assert event.error is not None and event.error.type == "timeout"
    assert [e for e in transcript().pending_events if e.event == "tool"] == []


@pytest.mark.anyio
async def test_parent_cancel_alone_finalizes_as_cancelled() -> None:
    """Control: a parent cancellation without an operator cancel."""
    import anyio

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    started = anyio.Event()
    handler = ToolCommand([_sleeper_tool("sleeper", started)]).service(
        state=_agent_state()
    )
    init_transcript(Transcript())

    async def call() -> None:
        await handler(tool="sleeper", arguments={})

    with anyio.fail_after(10):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call)
            await started.wait()
            tg.cancel_scope.cancel()

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.pending is None
    assert event.error is not None and event.error.message == "Tool call was cancelled."


def _many_parts_tool(text: str, parts: int, max_output: int, name: str = "many"):
    content = [ContentText(text=text)] * parts

    async def execute() -> list[ContentText]:
        """Return many large text parts.

        Returns:
            The parts.
        """
        return content

    return ToolDef(
        execute,
        name=name,
        description="Return many parts.",
        parameters={},
        max_output=max_output,
    ).as_tool()


@pytest.mark.anyio
@pytest.mark.parametrize("char", ["x", "é"], ids=["ascii", "multibyte"])
async def test_large_structured_result_renders_without_joining(char) -> None:
    """The terminal reply for a large multi-part result is built from the parts.

    Joining (and UTF-8 encoding) every part before capping allocated the
    whole result on the event loop: ~96 MiB extra for 32 x 1 MiB parts with
    max_output=1024.
    """
    import tracemalloc

    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    part = char * (1024 * 1024)
    handler = ToolCommand(
        [_many_parts_tool(part, 32, 1024), _many_parts_tool(char, 2, 1024, "warm")]
    ).service(state=_agent_state())
    init_transcript(Transcript())
    # the first call does one-time lazy initialisation (~19 MiB), which is
    # not rendering; measure a warm call
    await handler(tool="warm", arguments={})

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        result = str(await handler(tool="many", arguments={}))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 4 * 1024 * 1024, peak
    assert "truncated" in result
    assert len(result.encode()) < 4096
    event = next(
        e for e in transcript().events if e.event == "tool" and e.function == "many"
    )
    assert isinstance(event.result, list) and len(event.result) == 32


@pytest.mark.parametrize(
    "parts",
    [
        ["héllo wörld " * 50, "short", "ü" * 3000],
        ["a" * 10, "b" * 10],
        ["€" * 700],
        ["x" * 400, "é" * 400, "y" * 400],
        ["", "", "abc" * 100, ""],
        ["é"] * 900,
        ["\n" * 50, "z" * 500, "\n" * 50],
    ],
)
@pytest.mark.parametrize("limit", [16, 64, 1000, 5000])
def test_bounded_rendering_matches_full_rendering(parts, limit) -> None:
    """The bounded terminal rendering equals truncating the full join."""
    from inspect_ai.agent._human.commands.tool import _terminal_text
    from inspect_ai.model._call_tools import truncate_tool_output

    full = "\n".join(parts)
    expected = truncate_tool_output("t", full, limit)
    assert _terminal_text("t", parts, limit) == (expected.output if expected else full)
