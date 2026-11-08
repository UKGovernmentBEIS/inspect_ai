from inspect_ai._display.core.rich import _dumb_terminal_size_kwargs, rich_initialise


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


def test_rich_initialise_keeps_a_render_hook_the_caller_registered():
    """A Live or Progress started before the eval must still be able to stop afterwards.

    ``rich.reconfigure()`` reinitializes the global console, which drops the render hook the
    caller's context pushed; leaving that context then pops from an empty list.
    """
    import rich

    console = rich.get_console()
    hook = lambda renderable, options: iter(())  # noqa: E731
    console.push_render_hook(hook)
    try:
        rich_initialise()

        assert list(getattr(console, "_render_hooks", [])) == [hook]
        console.pop_render_hook()
    finally:
        while getattr(console, "_render_hooks", None):
            console._render_hooks.pop()  # type: ignore[attr-defined]
