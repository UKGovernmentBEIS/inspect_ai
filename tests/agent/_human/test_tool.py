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
    """Mirror the generated handler's kwargs filter (drops None values)."""
    args = parser.parse_args(argv)
    return {
        k: v
        for k, v in vars(args).items()
        if k not in ("tool_name", "command") and v is not None
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
    result = await handler(_tool_name_="_addition", x=1, y=2)
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


# --- should-fix: complex-params schema help must render readably -------------


def test_complex_tool_help_shows_readable_schema() -> None:
    """The epilog schema must survive argparse's formatter un-wrapped."""
    _, namespace = _build_parsers([_process_config()])
    sub = namespace["tool_subparsers"].choices["_process_config"]
    help_text = sub.format_help()
    # RawDescriptionHelpFormatter preserves the json.dumps(indent=2) layout;
    # the default formatter collapses it into a single mangled paragraph.
    assert '  "type": "object",' in help_text


# --- should-fix: escape hatch guards ------------------------------------------


def _run_escape_hatch(argv: list[str]) -> tuple[list, list, int | None]:
    """Exec the escape-hatch pre-parse snippet the way the sandbox script does."""
    from inspect_ai.agent._human.install import ESCAPE_HATCH_PREPARSE

    calls: list = []
    printed: list = []

    def call_human_agent(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "ok"

    import sys as real_sys
    import types

    fake_sys = types.SimpleNamespace(argv=argv, exit=real_sys.exit)
    namespace = {
        "sys": fake_sys,
        "call_human_agent": call_human_agent,
        "print": lambda *a: printed.append(" ".join(map(str, a))),
    }
    exit_code: int | None = None
    try:
        exec(compile(ESCAPE_HATCH_PREPARSE, "<escape-hatch>", "exec"), namespace)
    except SystemExit as ex:
        exit_code = int(ex.code or 0)
    return calls, printed, exit_code


def test_escape_hatch_rejects_non_dict_json() -> None:
    """A JSON array/scalar must produce a friendly error, not **-splat TypeError."""
    calls, printed, exit_code = _run_escape_hatch(
        ["task.py", "tool", "_addition", "--raw-json-escape-hatch", "[1, 2]"]
    )
    assert calls == []
    assert exit_code == 1
    assert any("JSON object" in line for line in printed)


def test_escape_hatch_rejects_reserved_key() -> None:
    """A JSON key colliding with the internal _tool_name_ kwarg must error cleanly."""
    calls, printed, exit_code = _run_escape_hatch(
        [
            "task.py",
            "tool",
            "_addition",
            "--raw-json-escape-hatch",
            '{"_tool_name_": "x"}',
        ]
    )
    assert calls == []
    assert exit_code == 1
    assert any("_tool_name_" in line for line in printed)


@pytest.mark.anyio
async def test_service_records_tool_event_on_error() -> None:
    """A failing tool call must still be recorded (with its error)."""
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.tool import ToolError

    @tool
    def _boom():
        async def execute() -> str:
            """Always fails.

            Returns:
                Never returns.
            """
            raise ToolError("kaboom")

        return execute

    command = ToolCommand([_boom()])
    handler = command.service(state=None)  # type: ignore[arg-type]

    init_transcript(Transcript())
    with pytest.raises(ToolError):
        await handler(_tool_name_="_boom")

    tool_events = [e for e in transcript().events if e.event == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0].error is not None
    assert "kaboom" in tool_events[0].error.message
