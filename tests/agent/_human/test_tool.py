import argparse

import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._human.commands.tool import ToolCommand, tool_result_to_str
from inspect_ai.tool import ToolDef, tool
from inspect_ai.util import JSONSchema


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
    handler = command.service(state=None)  # type: ignore[arg-type]

    init_transcript(Transcript())
    result = await handler(tool="_addition", arguments={"x": 1, "y": 2})
    assert result == "3"

    tool_events = [e for e in transcript().events if e.event == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0].function == "_addition"
    assert tool_events[0].arguments == {"x": 1, "y": 2}
    assert tool_events[0].result == 3


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

    handler = ToolCommand([_named_tool("find-item")]).service(state=None)  # type: ignore[arg-type]
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
    handler = command.service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    result = await handler(tool="hostile", arguments={"_tool_name_": "ok"})
    assert result == "ok"


# --- round 2: explicit JSON null must be expressible ------------------------


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


def test_explicit_null_for_nullable_scalar_is_sent() -> None:
    """--value null must parse for int|None (type=int rejected the token)."""
    parser, _ = _build_parsers([_maybe()])
    kwargs = _handler_kwargs(parser, ["tool", "_maybe", "--value", "null"])
    assert kwargs == {"value": None}


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

    handler = ToolCommand([_addition()]).service(state=None)  # type: ignore[arg-type]
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
    handler = ToolCommand([tool]).service(state=None)  # type: ignore[arg-type]
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
    handler = ToolCommand([tool]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    async def call() -> None:
        await handler(tool="tracker")

    async with anyio.create_task_group() as tg:
        tg.start_soon(call)
        tg.start_soon(call)
    assert active["max"] == 2


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

    handler = ToolCommand([viewed]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    await handler(tool="viewed", arguments={"x": 1, "y": 2})

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.view is not None
    assert "adding" in event.view.content


# --- round 7: sample waiting time is excluded from tool working time ---------


@pytest.mark.anyio
async def test_waiting_time_excluded_from_working_time() -> None:
    """Nested waits (model calls, rate limits) are not tool working time.

    Hard-coding waiting_time=0 counted a nested 50ms reported wait as
    work; the model path snapshots sample_waiting_time() and passes the
    delta at finalization.
    """
    from inspect_ai._util.working import report_sample_waiting_time
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

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

    handler = ToolCommand([waiter]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    await handler(tool="waiter", arguments={})

    event = next(e for e in transcript().events if e.event == "tool")
    assert event.working_time is not None
    assert 0 <= event.working_time < 0.04  # ~0.06 elapsed minus 0.05 waited


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

    handler = ToolCommand([grouped]).service(state=None)  # type: ignore[arg-type]
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

    handler = ToolCommand([limited]).service(state=None)  # type: ignore[arg-type]
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

    handler = ToolCommand([failing]).service(state=None)  # type: ignore[arg-type]
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


def test_null_advertised_only_where_supported() -> None:
    """Arrays and booleans have no null spelling — help must not offer one.

    Nullable scalars and JSON values accept the null literal; nullable
    arrays reject it during item conversion and nullable booleans have
    only --flag/--no-flag. Advertising null there documents a lie.
    """
    code = ToolCommand([_nullable_menagerie()]).get_cli_parser_code()
    args = {
        name: next(ln for ln in code.splitlines() if f"dest='arg_{name}'" in ln)
        for name in ("value", "tags", "strict")
    }
    assert "'null' for null" in args["value"]
    assert "'null' for null" not in args["tags"]
    assert "'null' for null" not in args["strict"]


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
    kwargs = _handler_kwargs(parser, ["tool", "req_nullable", "--value", "null"])
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
    handler = ToolCommand([_kwargs_tool(prop)]).service(state=None)  # type: ignore[arg-type]
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

    handler = ToolCommand([leveled]).service(state=None)  # type: ignore[arg-type]
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
async def test_ordinary_exception_surfaces_and_records() -> None:
    """A tool raising a non-ToolError surfaces a clean message and records.

    Raising through the sandbox-service boundary just hands the human a
    raw RPC traceback (the boundary swallows the exception and polls
    on), and terminating the sample would destroy hours of human work
    over a possibly-incidental tool bug. Instead: readable CLI message,
    failed ToolEvent in the transcript, session continues.
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

    handler = ToolCommand([broken]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    result = await handler(tool="broken", arguments={})

    assert "Error executing tool 'broken'" in str(result)
    assert "boom" in str(result)
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None
    assert "boom" in events[0].error.message
    assert events[0].failed is True


@pytest.mark.anyio
async def test_finalized_event_leaves_pending_registry() -> None:
    """Finalization must publish the update, not just mutate the event.

    _set_result() without transcript()._event_updated() leaves the
    completed event registered pending: live subscribers never see the
    completion and bounded transcripts pin the event forever.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    handler = ToolCommand([_addition()]).service(state=None)  # type: ignore[arg-type]
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

    handler = ToolCommand([dated]).service(state=None)  # type: ignore[arg-type]
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

    handler = ToolCommand([observer]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    await handler(tool="observer", arguments={})

    assert seen["count"] == 1
    assert seen["pending"] is True
    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].pending is None  # finalized
    assert events[0].completed is not None
