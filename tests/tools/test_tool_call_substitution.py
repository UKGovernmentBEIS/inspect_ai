from dataclasses import dataclass, field
from unittest.mock import patch

from pydantic import JsonValue
from rich.text import Text

from inspect_ai.tool._tool_call import (
    ToolCallContent,
    ToolCallView,
    substitute_tool_call_content,
)


class TestSubstituteToolCallContent:
    def test_basic_substitution(self) -> None:
        content = ToolCallContent(
            title="Run {{command}}",
            format="text",
            content="Executing: {{command}}",
        )
        result = substitute_tool_call_content(content, {"command": "ls -la"})
        assert result.title == "Run ls -la"
        assert result.content == "Executing: ls -la"

    def test_missing_key_left_as_is(self) -> None:
        content = ToolCallContent(
            title="{{missing}}",
            format="text",
            content="Value: {{missing}}",
        )
        result = substitute_tool_call_content(content, {"other": "val"})
        assert result.title == "{{missing}}"
        assert result.content == "Value: {{missing}}"

    def test_title_and_content_both_substituted(self) -> None:
        content = ToolCallContent(
            title="{{action}} {{target}}",
            format="markdown",
            content="# {{action}}\nTarget: {{target}}",
        )
        result = substitute_tool_call_content(
            content, {"action": "Delete", "target": "file.txt"}
        )
        assert result.title == "Delete file.txt"
        assert result.content == "# Delete\nTarget: file.txt"

    def test_rich_markup_in_values(self) -> None:
        content = ToolCallContent(
            title="Code: {{code}}",
            format="text",
            content="{{code}}",
        )
        result = substitute_tool_call_content(content, {"code": "[red]danger[/red]"})
        assert result.title == "Code: [red]danger[/red]"
        assert result.content == "[red]danger[/red]"

    def test_empty_arguments(self) -> None:
        content = ToolCallContent(
            title="{{key}}",
            format="text",
            content="Hello {{key}}",
        )
        result = substitute_tool_call_content(content, {})
        assert result.title == "{{key}}"
        assert result.content == "Hello {{key}}"

    def test_none_title(self) -> None:
        content = ToolCallContent(
            format="text",
            content="Value: {{x}}",
        )
        result = substitute_tool_call_content(content, {"x": "42"})
        assert result.title is None
        assert result.content == "Value: 42"

    def test_original_not_mutated(self) -> None:
        content = ToolCallContent(
            title="{{key}}",
            format="text",
            content="{{key}}",
        )
        substitute_tool_call_content(content, {"key": "val"})
        assert content.title == "{{key}}"
        assert content.content == "{{key}}"


class TestToolViewAsStr:
    def test_substituted_content(self) -> None:
        from inspect_ai.analysis._dataframe.events.extract import tool_view_as_str
        from inspect_ai.event._tool import ToolEvent

        event = ToolEvent(
            id="1",
            function="code",
            arguments={"code": "print('hello')"},
            view=ToolCallContent(
                title="Code: {{code}}",
                format="text",
                content="{{code}}",
            ),
        )
        result = tool_view_as_str(event)
        assert result == "Code: print('hello')\n\nprint('hello')"

    def test_none_view(self) -> None:
        from inspect_ai.analysis._dataframe.events.extract import tool_view_as_str
        from inspect_ai.event._tool import ToolEvent

        event = ToolEvent(
            id="1",
            function="code",
            arguments={"code": "x"},
        )
        assert tool_view_as_str(event) is None


@dataclass
class _FakeTranscriptToolCall:
    function: str
    arguments: dict[str, JsonValue]
    view: ToolCallContent | None = field(default=None)


class TestTranscriptToolCallEscaping:
    def test_markup_in_title_no_error(self) -> None:
        from inspect_ai.tool._tool_transcript import transcript_tool_call

        call = _FakeTranscriptToolCall(
            function="run_code",
            arguments={"code": "[red]danger[/red]"},
            view=ToolCallContent(
                title="Code: {{code}}",
                format="text",
                content="{{code}}",
            ),
        )
        result = transcript_tool_call(call)
        assert len(result) > 0
        title_text = result[0]
        assert isinstance(title_text, Text)
        assert "[red]danger[/red]" in title_text.plain


class TestRenderToolApprovalEscaping:
    @patch("inspect_ai.approval._human.util.display_type", return_value="full")
    def test_markup_in_title_no_error(self, _mock_display: object) -> None:
        from inspect_ai.approval._human.util import render_tool_approval

        view = ToolCallView(
            call=ToolCallContent(
                title="Run: {{cmd}}",
                format="text",
                content="{{cmd}}",
            ),
        )
        result = render_tool_approval(
            message="Please approve",
            view=view,
            arguments={"cmd": "[bold]evil[/bold]"},
        )
        assert len(result) > 0
        # Find the Text renderable containing the title (has "Run:" prefix)
        title_texts = [r for r in result if isinstance(r, Text) and "Run:" in r.plain]
        assert len(title_texts) == 1
        assert "[bold]evil[/bold]" in title_texts[0].plain
