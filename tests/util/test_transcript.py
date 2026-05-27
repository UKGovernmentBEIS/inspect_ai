from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.content import ContentReasoning
from inspect_ai._util.transcript import content_display, transcript_reasoning


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
