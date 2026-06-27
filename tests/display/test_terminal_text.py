import io
import unicodedata

from rich.console import Console
from rich.style import Style
from rich.text import Text

from inspect_ai._display.core.config import task_config
from inspect_ai._display.core.display import TaskProfile
from inspect_ai._display.core.panel import task_panel
from inspect_ai._display.textual.widgets.transcript import (
    render_error_event,
    render_score_event,
)
from inspect_ai._util.error import EvalError
from inspect_ai._util.rich import (
    clean_control_characters,
    rich_traceback,
    untrusted_text_from_ansi,
)
from inspect_ai._util.transcript import transcript_markdown
from inspect_ai.agent._acp.tui.state import ScoreChip
from inspect_ai.agent._acp.tui.widgets._collapsible import CollapsibleContent
from inspect_ai.agent._acp.tui.widgets.markdown import StyledMarkdown
from inspect_ai.agent._acp.tui.widgets.score import ScoreChipWidget
from inspect_ai.event import ErrorEvent, ScoreEvent
from inspect_ai.log import EvalConfig
from inspect_ai.model import GenerateConfig, ModelName
from inspect_ai.scorer import Score

PAYLOAD = (
    "VISIBLE-BEFORE"
    "\x1b[2J"
    "\x1b[H"
    "FORGED-SCREEN"
    "\x1b]52;c;UEFTVEVfSElKQUNL\x07"
    "\x1b]8;;file:///etc/passwd\x1b\\"
    "DISGUISED-LINK"
    "\x1b]8;;\x1b\\"
    "\x9b2J"
    "\x9d52;c;UEFTVEVfSElKQUNL\x9c"
    "\r\b\x00\x7f"
    "VISIBLE-AFTER"
    "\nNEXT\tCELL"
)


def _render(renderable: object) -> str:
    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=False,
        color_system=None,
        width=1000,
    )
    console.print(renderable)
    return stream.getvalue()


def _assert_safe(text: str) -> None:
    assert all(
        char in "\n\t" or unicodedata.category(char) not in ("Cc", "Cf")
        for char in text
    )
    assert "VISIBLE-BEFORE" in text
    assert "VISIBLE-AFTER" in text


def test_clean_control_characters_preserves_visible_text_and_whitespace() -> None:
    cleaned = clean_control_characters(PAYLOAD)

    _assert_safe(cleaned)
    assert "\nNEXT\tCELL" in cleaned


def test_transcript_markdown_removes_terminal_controls() -> None:
    output = _render(transcript_markdown(PAYLOAD, escape=True))

    _assert_safe(output)


def test_score_event_removes_controls_from_all_text_fields() -> None:
    event = ScoreEvent(
        score=Score(
            value=PAYLOAD,
            answer=PAYLOAD,
            explanation=PAYLOAD,
        ),
        target=PAYLOAD,
    )

    output = _render(render_score_event(event).content)

    _assert_safe(output)
    assert output.count("VISIBLE-BEFORE") == 4


def test_error_event_and_rich_traceback_remove_terminal_controls() -> None:
    event = ErrorEvent(
        error=EvalError(
            message=PAYLOAD,
            traceback=PAYLOAD,
            traceback_ansi=PAYLOAD,
        )
    )
    _assert_safe(_render(render_error_event(event).content))

    try:
        raise RuntimeError(PAYLOAD)
    except RuntimeError as ex:
        output = _render(rich_traceback(type(ex), ex, ex.__traceback__))

    _assert_safe(output)


def test_task_panel_cleans_metadata_and_filename_content() -> None:
    profile = TaskProfile(
        name=PAYLOAD,
        file=None,
        model=ModelName("mockllm/model"),
        agent=None,
        dataset=PAYLOAD,
        scorer=PAYLOAD,
        samples=1,
        steps=1,
        eval_config=EvalConfig(),
        task_args={"metadata": PAYLOAD},
        generate_config=GenerateConfig(),
        tags=None,
        log_location=f"/tmp/{PAYLOAD}.eval",
        task_id="task",
        task_cancel=None,
    )
    panel = task_panel(
        profile=profile,
        show_model=True,
        body=Text(PAYLOAD),
        subtitle=task_config(profile),
        footer=None,
        log_location=profile.log_location,
    )

    _assert_safe(_render(panel))


def test_untrusted_ansi_keeps_visual_style_but_drops_links_and_controls() -> None:
    text = untrusted_text_from_ansi(f"\x1b[31mred\x1b[0m {PAYLOAD}")

    _assert_safe(text.plain)
    assert any(
        isinstance(span.style, Style) and span.style.color is not None
        for span in text.spans
    )
    assert all(
        not isinstance(span.style, Style) or span.style.link is None
        for span in text.spans
    )


def test_acp_markdown_and_collapsible_content_clean_before_layout() -> None:
    markdown = StyledMarkdown(PAYLOAD)
    collapsible = CollapsibleContent(PAYLOAD, max_lines=5)

    _assert_safe(markdown.markup)
    _assert_safe(collapsible._full_text)


def test_acp_score_header_removes_controls() -> None:
    chip = ScoreChip(
        scorer=PAYLOAD,
        value=PAYLOAD,
        passed=None,
        answer=None,
        reason=None,
        chip_id="score",
    )

    output = ScoreChipWidget(chip)._chip_text()

    _assert_safe(output)
