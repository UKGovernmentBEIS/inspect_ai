import pytest
from rich.console import Console

from inspect_ai._display.core.results import task_stats
from inspect_ai._display.core.rich import _dumb_terminal_size_kwargs
from inspect_ai._display.log.display import LogDisplay
from inspect_ai.log import EvalStats


@pytest.mark.parametrize(
    "started,completed",
    [
        ("2026-10-02T12:00:00+00:00", "2026-10-02T12:00:01+00:00"),
        ("2026-10-02T12:00:00+00:00", ""),
        ("", ""),
    ],
)
def test_stats_completion_display(started: str, completed: str) -> None:
    stats = EvalStats.model_validate({"started_at": started, "completed_at": completed})
    console = Console(record=True, width=100)
    console.print(task_stats(stats))
    expected = "0:00:01" if completed else "unavailable"
    assert expected in console.export_text()
    assert expected in LogDisplay()._task_stats_str(stats)


def test_dumb_terminal_uses_columns_with_default_height(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "10000")
    monkeypatch.delenv("LINES", raising=False)

    assert _dumb_terminal_size_kwargs() == {"width": 10000, "height": 25}


def test_dumb_terminal_uses_lines_when_available(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LINES", "50")

    assert _dumb_terminal_size_kwargs() == {"width": 200, "height": 50}


def test_terminal_size_override_requires_dumb_term(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LINES", "50")

    assert _dumb_terminal_size_kwargs() == {}
