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
    is_interactive: bool = True,
) -> SimpleNamespace:
    acp = SimpleNamespace(
        session_id=session_id,
        interrupt_pending=interrupt_pending,
        is_interactive=is_interactive,
    )
    return SimpleNamespace(acp_transport=acp, interrupt_action=interrupt_action)


def _interrupt_btn_visible(sample: SimpleNamespace | None, *, in_prompt: bool) -> bool:
    """Mirror of SampleInfo.sync_sample's interrupt-button visibility gate.

    Kept in lockstep with the predicate in
    ``inspect_ai._display.textual.widgets.samples.SampleInfo.sync_sample`` so
    the bug it guards against — the button showing for samples with no bound,
    live agent loop — has direct regression coverage without a mounted app.
    """
    acp = sample.acp_transport if sample is not None else None
    return acp is not None and acp.is_interactive and not in_prompt


def test_interrupt_button_hidden_without_interactive_session():
    # A Live ACP session is opened for *every* sample (even plain solver tasks),
    # so acp_transport is non-None with a real session_id. The button must gate
    # on is_interactive (a bound, live agent loop), not on session existence.
    plain = _fake_sample(None, is_interactive=False)
    assert not _interrupt_btn_visible(plain, in_prompt=False)


def test_interrupt_button_shown_for_interactive_session():
    agent = _fake_sample(None, is_interactive=True)
    assert _interrupt_btn_visible(agent, in_prompt=False)


def test_interrupt_button_hidden_when_no_sample():
    assert not _interrupt_btn_visible(None, in_prompt=False)


def test_interrupt_button_hidden_in_prompt_mode():
    # Even an interactive session hides the button while injecting, so a repeat
    # click can't fire a duplicate cancel before the operator submits.
    agent = _fake_sample(None, is_interactive=True)
    assert not _interrupt_btn_visible(agent, in_prompt=True)


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
