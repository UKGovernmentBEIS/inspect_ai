from inspect_ai._display.core.rich import _dumb_terminal_size_kwargs


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
