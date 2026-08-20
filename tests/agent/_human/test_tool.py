import argparse

import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._human.commands.tool import ToolCommand, tool_result_to_str
from inspect_ai.tool import ToolDef, tool


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
    """Mirror the generated handler's tool-args extraction (drops None values)."""
    args = parser.parse_args(argv)
    return {
        k[len("arg_") :]: v
        for k, v in vars(args).items()
        if k.startswith("arg_") and v is not None
    }


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


def test_tool_name_must_be_python_identifier() -> None:
    """Non-identifier tool names are rejected at construction.

    They would break (or inject into) the generated sandbox script.
    """
    with pytest.raises(ValueError, match="identifier"):
        ToolCommand([_named_tool("my-tool")])


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
                "level": JSONSchema(
                    type="integer", minimum=1, description="The level."
                )
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
async def test_ordinary_exception_still_records_event() -> None:
    """A tool raising a non-ToolError must still leave a transcript event.

    Only ToolError was caught, so a plain RuntimeError propagated with
    zero events — the human's failed invocation vanished from the data.
    """
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    async def execute() -> str:
        """Raise an ordinary exception.

        Returns:
            Never returns.
        """
        raise RuntimeError("boom")

    broken = ToolDef(
        execute, name="broken", description="Raise an ordinary exception.", parameters={}
    ).as_tool()

    handler = ToolCommand([broken]).service(state=None)  # type: ignore[arg-type]
    init_transcript(Transcript())
    with pytest.raises(RuntimeError, match="boom"):
        await handler(tool="broken", arguments={})

    events = [e for e in transcript().events if e.event == "tool"]
    assert len(events) == 1
    assert events[0].error is not None
    assert "boom" in events[0].error.message


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
