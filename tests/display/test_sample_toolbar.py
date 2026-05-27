from types import SimpleNamespace

from inspect_ai._display.textual.widgets.samples import SampleToolbar


def _toolbar_with_recording_prompt_mode() -> tuple[SampleToolbar, list[object]]:
    toolbar = SampleToolbar()
    entered: list[object] = []
    toolbar.enter_prompt_mode = lambda sample: entered.append(sample)  # type: ignore[method-assign]
    toolbar._prompt_mode = False
    return toolbar, entered


def _fake_sample(
    interrupt_action: str | None,
    *,
    interrupt_pending: bool = True,
    session_id: str = "s1",
) -> SimpleNamespace:
    acp = SimpleNamespace(session_id=session_id, interrupt_pending=interrupt_pending)
    return SimpleNamespace(acp_transport=acp, interrupt_action=interrupt_action)


def test_handle_interrupted_skips_prompt_on_terminal_cancel():
    # Cancel (Score)/(Error) sets interrupt_action and routes through the
    # same cancel_current_turn() -> mark_interrupted() path as a pause-to-
    # inject interrupt. The sample is being torn down for scoring, so the
    # interject input bar must NOT pop (it would otherwise linger until
    # scoring completes).
    for action in ("score", "error"):
        toolbar, entered = _toolbar_with_recording_prompt_mode()
        toolbar.sample = _fake_sample(action)
        toolbar._handle_interrupted("s1")
        assert entered == [], f"prompt mode entered on {action} cancel"


def test_handle_interrupted_enters_prompt_on_pause_inject():
    # A pause-to-inject interrupt (Interrupt button, or a sibling ACP
    # client) never calls sample.interrupt(), so interrupt_action is None
    # and prompt mode should engage.
    toolbar, entered = _toolbar_with_recording_prompt_mode()
    sample = _fake_sample(None)
    toolbar.sample = sample
    toolbar._handle_interrupted("s1")
    assert entered == [sample]
