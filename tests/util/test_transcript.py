from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.content import ContentReasoning
from inspect_ai._util.transcript import (
    content_display,
    html_escape_markdown,
    transcript_reasoning,
)


def test_content_display_no_truncation():
    text = "hello world"
    result = content_display(text, max_lines=10)
    assert len(result) == 1
    assert isinstance(result[0], Markdown)
    assert result[0].markup == "hello world"


def test_content_display_truncates():
    text = "\n".join(f"line{i}" for i in range(20))
    result = content_display(text, max_lines=5)
    # markdown with truncated text + spacer + truncation notice
    assert len(result) == 3
    assert isinstance(result[0], Markdown)
    assert result[0].markup == "line0\nline1\nline2\nline3\nline4"
    assert isinstance(result[2], Text)
    assert "Content truncated" in result[2].markup
    assert "15 additional lines" in result[2].markup


def test_content_display_exact_limit():
    text = "\n".join(f"line{i}" for i in range(5))
    result = content_display(text, max_lines=5)
    # exactly at limit, no truncation
    assert len(result) == 1
    assert isinstance(result[0], Markdown)
    assert result[0].markup == "line0\nline1\nline2\nline3\nline4"


def test_transcript_reasoning_short():
    text = "short reasoning text"
    result = transcript_reasoning(ContentReasoning(reasoning=text))
    assert len(result) == 2
    assert isinstance(result[0], Markdown)
    # contains the reasoning wrapped in <think> tags
    assert "short reasoning text" in result[0].markup
    assert "think" in result[0].markup
    # no truncation notice
    assert "Content truncated" not in result[0].markup


def test_transcript_reasoning_truncates():
    text = "\n".join(f"thought{i}" for i in range(60))
    result = transcript_reasoning(ContentReasoning(reasoning=text))
    assert len(result) == 2
    assert isinstance(result[0], Markdown)
    # first 50 lines are present
    assert "thought0" in result[0].markup
    assert "thought49" in result[0].markup
    # lines beyond the limit are not present
    assert "thought50" not in result[0].markup
    # truncation notice is embedded inside the think block
    assert "Content truncated" in result[0].markup
    assert "10 additional lines" in result[0].markup
    # think tags still wrap the content (HTML-escaped)
    assert "&lt;think&gt;" in result[0].markup
    assert "&lt;/think&gt;" in result[0].markup


def test_transcript_reasoning_empty():
    result = transcript_reasoning(ContentReasoning(reasoning=""))
    assert result == []


def test_transcript_reasoning_redacted():
    result = transcript_reasoning(ContentReasoning(reasoning="", redacted=True))
    assert len(result) == 2
    assert isinstance(result[0], Markdown)
    assert "Reasoning encrypted by model provider." in result[0].markup


def test_html_escape_markdown_escapes_outside_codeblocks():
    assert "&lt;b&gt;hi&lt;/b&gt;" in html_escape_markdown("<b>hi</b>")


def test_html_escape_markdown_preserves_codeblock_contents():
    result = html_escape_markdown("```\n<b>code</b>\n```")
    # content inside a fenced block is left as-is (not escaped)
    assert "<b>code</b>" in result


def test_html_escape_markdown_backticks_in_string_do_not_break_fence():
    # A "```" string literal inside the code block must not close the block;
    # the <b> tag after the real closing fence is outside it and must be escaped.
    content = '```python\na = "```"\n```\n<b>dangerous</b>'
    result = html_escape_markdown(content)
    assert "&lt;b&gt;dangerous&lt;/b&gt;" in result
    assert "<b>dangerous</b>" not in result


def test_html_escape_markdown_list_nested_fence():
    # A fence opened inside a list item used to invert the fence state:
    # the opener went undetected but the closing line re-opened a phantom
    # block, leaving everything after the list unescaped.
    content = "- ```python\n  x < 1\n  ```\nAfter the list: <script>alert(1)</script>"
    result = html_escape_markdown(content)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_html_escape_markdown_info_string_is_not_a_closer():
    # CommonMark closing fences may carry only trailing spaces, so ```python
    # does not close an open block; the block stays open through the last
    # line and nothing after it leaks out unescaped.
    content = "```\n```python\ncode\n```\n<b>after</b>"
    result = html_escape_markdown(content)
    assert "<b>after</b>" not in result
    assert "&lt;b&gt;after&lt;/b&gt;" in result


def test_html_escape_markdown_indented_backticks_are_not_a_fence():
    # Backticks indented four or more spaces are an indented code block, not
    # a fence opener; the lines after it are ordinary text and must be escaped.
    content = "    ```\nsome text\n<b>hidden</b>"
    result = html_escape_markdown(content)
    assert "<b>hidden</b>" not in result
    assert "&lt;b&gt;hidden&lt;/b&gt;" in result


def test_html_escape_markdown_unicode_line_separator_does_not_shift_indices():
    # str.splitlines() breaks on U+2028 (and \v, \f, U+2029, ...), but the
    # CommonMark tokenizer counts lines only by \n. Counting with splitlines()
    # would shift our indices out of step with token.map, so the leading U+2028
    # here would land <script> on a line the fence tokens claim, leaving it raw.
    content = "\u2028<script>alert(1)</script>\n```python\ncode\n```"
    result = html_escape_markdown(content)
    assert "<script>alert(1)</script>" not in result
    assert "&lt;script&gt;" in result
