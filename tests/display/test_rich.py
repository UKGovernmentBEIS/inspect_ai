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


def test_rich_initialise_keeps_a_render_hook_the_caller_registered(monkeypatch):
    """A host that registered a render hook can still pop it after the eval."""
    import rich
    from rich.console import Console

    console = Console(force_terminal=False)
    monkeypatch.setattr(rich, "_console", console)
    hook = lambda renderable, options: iter(())  # noqa: E731
    console.push_render_hook(hook)

    rich_initialise(display="none", plain=True)

    assert rich.get_console() is console
    assert list(getattr(console, "_render_hooks", [])) == [hook]
    console.pop_render_hook()


def test_rich_initialise_keeps_a_hosts_progress_context_usable(monkeypatch):
    """Entering an eval inside a host context must not break leaving that context.

    ``rich.reconfigure()`` drops the render hook the ``Progress`` pushed, so ``__exit__``
    would pop from an empty list.
    """
    import rich
    from rich.console import Console
    from rich.progress import Progress

    monkeypatch.setattr(rich, "_console", Console(force_terminal=False))

    with Progress(redirect_stdout=False, redirect_stderr=False) as progress:
        progress.add_task("host", total=1)
        rich_initialise(display="none", plain=True)

        console = rich.get_console()
        assert getattr(console, "_render_hooks", [])
