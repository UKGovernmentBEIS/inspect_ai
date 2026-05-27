"""Pilot tests for the bare SessionScreen (Phase 1).

Textual's ``App.run_test()`` driver is asyncio-only; trio variants
are skipped via ``@skip_if_trio``.

Every test in this module spins up a Textual app via ``run_test`` —
that's ~100ms of framework setup per test, which adds up during
iteration. The module-level ``pytestmark`` opts the file into the
``slow`` marker so these tests only run with ``--runslow``; pure unit
tests for the picker live in :mod:`test_picker_screen` (the fast
helper tests at the top of the file) and run on every collection.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from test_helpers.utils import skip_if_trio
from textual.binding import Binding
from textual.widgets import Static, TextArea

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen

from .conftest import make_fake_client

pytestmark = pytest.mark.slow


def _bindings_by_key() -> dict[str, Binding]:
    """Return a key→Binding map for SessionScreen's BINDINGS.

    ``ClassVar[BINDINGS]`` is typed as the union ``Binding |
    tuple[str, str] | tuple[str, str, str]`` upstream so subclasses
    can use the shorthand tuple form. SessionScreen's bindings are
    all the ``Binding`` form, so filter to narrow before the tests
    poke at the structured attributes.
    """
    return {b.key: b for b in SessionScreen.BINDINGS if isinstance(b, Binding)}


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_meta_row_renders_all_fields(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Drive the row select directly.
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        meta = app.screen.query_one("#meta-text", Static)
        # ``meta.content`` returns the raw markup (with [dim]…[/dim]);
        # render the markup so assertions match what the user actually
        # sees on screen.
        text = meta.render_str(str(meta.content)).plain
        # ``inspect acp`` and ``eval-aaa`` are intentionally absent —
        # the window title carries the app name, and the eval id is
        # implicit from the picked session. Field labels precede each
        # value.
        assert "inspect acp" not in text
        assert "eval-aaa" not in text
        assert "task: my_task" in text
        # sample/epoch fused as one field — epoch is a sub-key of sample.
        assert "sample: 0/1" in text
        assert "epoch" not in text
        assert "agent: react" in text


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_meta_row_handles_missing_agent_name(
    sample_rows: list[SessionRow],
) -> None:
    """Older evals (or solver-less configs) leave agent_name unset."""
    rows = [
        SessionRow(
            eval_id=sample_rows[0].eval_id,
            session_id=sample_rows[0].session_id,
            task=sample_rows[0].task,
            sample_id=sample_rows[0].sample_id,
            epoch=sample_rows[0].epoch,
            agent_name=None,  # the case under test
            started_at=sample_rows[0].started_at,
            target=sample_rows[0].target,
        )
    ]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        meta = app.screen.query_one("#meta-text", Static)
        # Em-dash placeholder rather than a literal "None".
        text = meta.render_str(str(meta.content)).plain
        assert "agent: —" in text


@skip_if_trio
@pytest.mark.anyio
async def test_composer_has_top_margin_for_separation_from_transcript(
    sample_rows: list[SessionRow],
) -> None:
    """Composer wrapper must not sit flush against the widget above.

    A top margin of 1 keeps the composer visually separated from
    whatever's directly above (plan strip when visible, transcript
    otherwise) — collapsing it caused the plan overlay to render
    on top of the composer chrome.
    """
    from textual.containers import Horizontal

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        composer_row = app.screen.query_one("#composer-row", Horizontal)
        assert composer_row.styles.margin.top == 1


@skip_if_trio
@pytest.mark.anyio
async def test_composer_text_area_grows_but_caps_height(
    sample_rows: list[SessionRow],
) -> None:
    """The multi-line composer should grow without taking over the transcript."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        height = composer.styles.height
        min_height = composer.styles.min_height
        max_height = composer.styles.max_height
        assert height is not None and min_height is not None and max_height is not None
        assert height.is_auto
        assert min_height.value == 1
        assert max_height.value == 8


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_switch_sample_returns_to_picker(
    sample_rows: list[SessionRow],
) -> None:
    """^S on the session screen disconnects and returns to the picker.

    Also pins the no-toast invariant: the user-initiated path must not
    surface the "disconnected from server" warning the watcher fires
    on peer-side EOF.
    """
    from inspect_ai.agent._acp.tui.picker_screen import PickerScreen

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    notifications: list[tuple[str, str | None]] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Capture any notify() calls so we can assert the toast doesn't
        # fire on the user-initiated path.
        original_notify = app.notify

        def _capture(message: str, *args: Any, **kwargs: Any) -> None:
            notifications.append((message, kwargs.get("severity")))
            original_notify(message, *args, **kwargs)

        app.notify = _capture  # type: ignore[method-assign]

        app.screen.action_switch_sample()
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, PickerScreen):
                break
        assert isinstance(app.screen, PickerScreen)
        assert cast(Any, app)._attached is None
        # No "disconnected from server" toast — the user knows they
        # asked to switch.
        assert not any("disconnected" in msg.lower() for msg, _ in notifications), (
            notifications
        )


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_ctrl_s_to_switch_sample(
    sample_rows: list[SessionRow],
) -> None:
    """The ^S binding must exist on SessionScreen with the right action."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        by_key = _bindings_by_key()
        assert "ctrl+s" in by_key, "expected a ctrl+s binding on SessionScreen"
        assert by_key["ctrl+s"].action == "switch_sample"
        # show=True so the Footer hint surfaces.
        assert by_key["ctrl+s"].show is True


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_enter_and_escape(
    sample_rows: list[SessionRow],
) -> None:
    """↵ submit / Esc interrupt must appear in the Footer keymap."""
    by_key = _bindings_by_key()
    assert "enter" in by_key
    assert by_key["enter"].action == "submit"
    assert by_key["enter"].show is True
    assert by_key["enter"].priority is False
    assert "escape" in by_key
    assert by_key["escape"].action == "interrupt"
    assert by_key["escape"].show is True
    assert by_key["escape"].priority is True


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_shift_enter_to_newline(
    sample_rows: list[SessionRow],
) -> None:
    r"""⇧↵ newline must surface in the Footer with a ``\n``-inserting action.

    The composer is a ``TextArea`` now, so the inserted newline is
    visible locally and ships as part of the submitted prompt.
    """
    by_key = _bindings_by_key()
    assert "shift+enter" in by_key
    assert by_key["shift+enter"].action == "newline"
    assert by_key["shift+enter"].show is True
    assert by_key["shift+enter"].key_display == "⇧↵"
    assert by_key["shift+enter"].priority is True


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_ctrl_j_to_hidden_newline_fallback(
    sample_rows: list[SessionRow],
) -> None:
    """Ctrl+J is a hidden newline fallback for terminals without Shift+Enter."""
    by_key = _bindings_by_key()
    assert "ctrl+j" in by_key
    assert by_key["ctrl+j"].action == "newline"
    assert by_key["ctrl+j"].show is False
    assert by_key["ctrl+j"].priority is True


@skip_if_trio
@pytest.mark.anyio
async def test_action_newline_inserts_literal_newline_into_composer(
    sample_rows: list[SessionRow],
) -> None:
    r"""``action_newline`` writes ``\n`` at the cursor without submitting."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "line one"
        composer.move_cursor((0, len(composer.text)))
        app.screen.action_newline()
        await pilot.pause()
        assert composer.text == "line one\n"
        # And no requests were sent — the newline is composer-local.
        # ``FakeConnection.requests`` records ``(method, params)``
        # tuples, so an empty list is the precise invariant.
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == []


@skip_if_trio
@pytest.mark.anyio
async def test_composer_enter_converts_terminal_shift_enter_backslash_to_newline(
    sample_rows: list[SessionRow],
) -> None:
    """Mac Terminal-style Shift+Enter should be handled in TextArea._on_key."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "line one\\"
        composer.move_cursor((0, len(composer.text)))
        composer.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert composer.text == "line one\n"
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == []


@skip_if_trio
@pytest.mark.anyio
async def test_composer_enter_submits_from_text_area_key_handler(
    sample_rows: list[SessionRow],
) -> None:
    """Plain Enter in the focused composer submits via ComposerTextArea."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "please continue"
        composer.move_cursor((0, len(composer.text)))
        composer.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == [
            (
                "session/prompt",
                {
                    "sessionId": sample_rows[0].session_id,
                    "prompt": [{"type": "text", "text": "please continue"}],
                },
            )
        ]
        assert composer.text == ""


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_sends_prompt_and_clears_composer(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        # Composer must be enabled — Phase 3 makes it interactive.
        assert composer.disabled is False
        composer.text = "  please continue  "
        await app.screen.action_submit()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == [
            (
                "session/prompt",
                {
                    "sessionId": sample_rows[0].session_id,
                    "prompt": [{"type": "text", "text": "please continue"}],
                },
            )
        ]
        assert composer.text == ""


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_with_focused_button_delegates_to_button(
    sample_rows: list[SessionRow],
) -> None:
    """Enter on a focused approval Button fires Button.Pressed, not the composer send.

    Pinned regression for the Tab+Enter approval path: if the screen
    submit action lands while an approval option has focus, it must
    activate the option rather than submit the composer's draft.
    Fix: detect the focused-Button case in ``action_submit`` and
    forward to ``Button.action_press`` — scoped to APPROVAL buttons
    (id prefix ``approve-opt-``) so unrelated buttons added later
    don't get programmatic-pressed.
    """
    from textual.widgets import Button

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Mount a focusable Button using the APPROVAL id prefix
        # (``approve-opt-…``) so the delegation guard recognises it.
        # Composer carries a draft so we can prove action_submit
        # does NOT submit it when an approval button has focus.
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "this draft must not be sent"
        pressed: list[Button] = []

        class _SpyButton(Button):
            def on_button_pressed(self, event: Button.Pressed) -> None:
                pressed.append(event.button)

        spy = _SpyButton("approve", id="approve-opt-spy")
        await app.screen.mount(spy)
        spy.focus()
        await pilot.pause()
        assert app.screen.focused is spy

        await app.screen.action_submit()
        await pilot.pause()

        # The button fired its Pressed event.
        assert pressed == [spy]
        # The composer's draft was NOT submitted to the server.
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == []
        # And the draft is still in the composer (not cleared).
        assert composer.text == "this draft must not be sent"


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_with_focused_non_approval_button_does_not_delegate(
    sample_rows: list[SessionRow],
) -> None:
    """Delegation is scoped to ``approve-opt-`` buttons; others go through composer path.

    Pinned because the earlier revision delegated to ANY focused
    Button, which would silently fire a programmatic press on a
    future non-approval button (confirm-disconnect dialog, error
    recovery, etc.) when the operator hit Enter in the composer
    context. Scoped delegation prevents that surprise.
    """
    from textual.widgets import Button

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "please continue"
        pressed: list[Button] = []

        class _SpyButton(Button):
            def on_button_pressed(self, event: Button.Pressed) -> None:
                pressed.append(event.button)

        # Non-approval id — delegation must NOT fire here.
        spy = _SpyButton("OK", id="some-other-button")
        await app.screen.mount(spy)
        spy.focus()
        await pilot.pause()

        await app.screen.action_submit()
        await pilot.pause()

        # The button was NOT programmatically pressed.
        assert pressed == []
        # The composer's draft WAS submitted (composer path took over).
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests and conn.requests[0][0] == "session/prompt"


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_with_empty_composer_is_noop(
    sample_rows: list[SessionRow],
) -> None:
    """Empty / whitespace-only composer must not fire a request."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "   "
        await app.screen.action_submit()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == []


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_clears_draft_when_composer_nonempty(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with text present clears the draft and does NOT cancel."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "draft text"
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.notifications == []
        assert composer.text == ""


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_sends_cancel_when_agent_working(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with no draft sends ``session/cancel`` only when the agent is working.

    Putting the SessionState's status into ``GENERATING`` by adding a
    pending message id mimics what happens when the server has signalled
    a model invocation start without a completion marker yet.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = ""
        # Force the status into GENERATING by injecting a pending
        # message id — the property reads from this set first.
        app.screen.state._pending_message_ids.add("pending-msg")
        assert app.screen.state.status == StatusState.GENERATING
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.notifications == [
            (
                "session/cancel",
                {"sessionId": sample_rows[0].session_id},
            )
        ]
        # Optimistic local clear must have fired so the pill stops
        # advertising GENERATING during the server's cancel propagation.
        # mypy narrowed status to GENERATING from the earlier assertion;
        # action_interrupt mutated it via mark_interrupted.
        assert app.screen.state.status == StatusState.AWAITING_INPUT  # type: ignore[comparison-overlap]
        assert app.screen.state._pending_message_ids == set()


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_is_noop_when_awaiting_input(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with no draft AND no in-flight work must NOT fire a cancel.

    The server's ``cancel_current_turn`` writes a ``between_turns``
    ``InterruptEvent`` to the transcript when there's nothing to
    cancel — a stray Esc here would otherwise pollute the log and
    flip interrupt state pending.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = ""
        assert app.screen.state.status == StatusState.AWAITING_INPUT
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.notifications == []


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_is_noop_during_quiescence_tail(
    sample_rows: list[SessionRow],
) -> None:
    """Esc must NOT cancel during the post-chunk quiescence window.

    Repro: a normal assistant chunk just arrived (so ``_last_chunk_at``
    is set, ``status`` reports GENERATING via the quiescence branch)
    but generation is actually finished — ``_pending_message_ids`` is
    empty and no tools are in flight. A stray Esc here would have hit
    the wire and made the server record a ``between_turns``
    InterruptEvent for the 2-second tail. The interrupt gate uses
    ``has_active_work`` instead of display status to avoid this.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = ""
        # Simulate the quiescence-tail state directly: chunk activity
        # within the quiescence window, but no pending event and no
        # tools in flight.
        app.screen.state._last_chunk_at = app.screen.state._now()
        assert app.screen.state.status == StatusState.GENERATING
        assert app.screen.state.has_active_work is False

        await app.screen.action_interrupt()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.notifications == []


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_lifecycle_pill_starts_idle_and_hidden(
    sample_rows: list[SessionRow],
) -> None:
    """Initial lifecycle is ``idle`` — pill carries the class but is hidden.

    Pins the "no chrome noise at rest" property — the pill exists
    only to signal change, so between turns (and at startup) it
    must not occupy a visible cell.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        pill = app.screen.query_one("#lifecycle-indicator", Static)
        assert pill.has_class("idle")
        # The ``.idle`` rule hides the pill via display: none — pin
        # the empty content as a proxy so future glyph tweaks don't
        # accidentally show something at rest.
        assert str(pill.content) == ""


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_lifecycle_pill_flips_to_running(
    sample_rows: list[SessionRow],
) -> None:
    """Pending model event flips pill to ``running`` AND adds esc hint to placeholder."""
    from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        # Inject a pending signal into state.
        chunk = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=""),
            message_id="m1",
            field_meta={"inspect.model_event_pending": True},
        )
        app.screen.state.consume(SessionNotification(session_id="sid", update=chunk))
        await pilot.pause()
        pill = app.screen.query_one("#lifecycle-indicator", Static)
        assert "running" in str(pill.content)
        assert pill.has_class("running")
        composer = app.screen.query_one("#composer", TextArea)
        assert "esc to interrupt" in str(composer.placeholder)


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_lifecycle_pill_flips_to_interrupted(
    sample_rows: list[SessionRow],
) -> None:
    """``mark_interrupted`` flips pill to ``interrupted`` AND drops esc hint from placeholder."""
    from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        # Pending first so the interrupt actually tears something down.
        chunk = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=""),
            message_id="m1",
            field_meta={"inspect.model_event_pending": True},
        )
        app.screen.state.consume(SessionNotification(session_id="sid", update=chunk))
        await pilot.pause()
        app.screen.state.mark_interrupted()
        await pilot.pause()
        pill = app.screen.query_one("#lifecycle-indicator", Static)
        assert "interrupted" in str(pill.content)
        assert pill.has_class("interrupted")
        composer = app.screen.query_one("#composer", TextArea)
        assert "esc to interrupt" not in str(composer.placeholder)


@skip_if_trio
@pytest.mark.anyio
async def test_peer_disconnect_marks_complete_and_closes_session(
    sample_rows: list[SessionRow],
) -> None:
    """Peer-side disconnect: complete + read-only + ``close()`` runs.

    Lifecycle flips to ``complete``, the composer goes read-only,
    and ``AttachedSession.close`` runs even though the screen stays
    mounted. Without the explicit ``close()`` in the watcher, the
    ACP Connection/Sender/Dispatcher/writer would leak — the screen
    no longer pops back to the picker, so ``on_unmount`` won't fire
    for a long time (or ever this session).
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        # Spy on close so we can assert it was called by the watcher.
        session = cast(Any, app.screen)._session
        close_calls: list[int] = []
        original_close = session.close

        async def _spy_close() -> None:
            close_calls.append(1)
            await original_close()

        session.close = _spy_close

        # Trigger peer-side disconnect — same signal the receive
        # loop sets on EOF / read error.
        session.disconnected.set()
        for _ in range(20):
            await pilot.pause()
            if (
                isinstance(app.screen, SessionScreen)
                and app.screen.state.lifecycle == "complete"
            ):
                break

        assert isinstance(app.screen, SessionScreen)
        assert app.screen.state.lifecycle == "complete"
        assert close_calls == [1]
        # Screen is still mounted (no auto-pop) so the operator can
        # read the transcript.
        # Composer goes read-only with the completion placeholder.
        composer = app.screen.query_one("#composer", TextArea)
        assert composer.disabled is True
        assert composer.placeholder == "sample complete"


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_is_noop_when_session_complete(
    sample_rows: list[SessionRow],
) -> None:
    """Stray ↵ after completion must not push into a dead pipe.

    Pins reviewer P2: the composer's ``disabled`` flag handles the
    typical case, but the priority binding could still land during a
    focus-change window — gate ``action_submit`` on lifecycle as
    belt + braces.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        # Force the lifecycle into ``complete`` without going through
        # the disconnect path so we isolate the submit-guard.
        app.screen.state.mark_complete()
        await pilot.pause()
        composer = app.screen.query_one("#composer", TextArea)
        # Bypass the disabled flag in the test by writing directly to
        # text (a TextArea.disabled wouldn't block programmatic writes).
        composer.text = "anything"
        await app.screen.action_submit()
        await pilot.pause()
        conn = cast(Any, cast(Any, app.screen)._session.connection)
        assert conn.requests == []
        # And the composer text is preserved — we didn't clear it.
        assert composer.text == "anything"


@skip_if_trio
@pytest.mark.anyio
async def test_action_newline_is_noop_when_session_complete(
    sample_rows: list[SessionRow],
) -> None:
    """Stray ⇧↵ after completion must not mutate the composer.

    Pins reviewer P3: ``shift+enter`` is priority-bound, so the
    composer's ``disabled`` flag alone doesn't block the binding
    from firing during a focus-change window. Without the
    lifecycle guard a read-only completed session could still
    accumulate locally-inserted newlines.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        app.screen.state.mark_complete()
        await pilot.pause()
        composer = app.screen.query_one("#composer", TextArea)
        # Pre-seed a value we can verify wasn't mutated.
        composer.text = "draft"
        composer.move_cursor((0, len(composer.text)))
        app.screen.action_newline()
        await pilot.pause()
        assert composer.text == "draft"


def _bar_pending_request(tool_call_id: str = "tc-1", *, title: str = "bash ls"):
    """Build a pending RequestPermissionRequest for action_approval_decide tests."""
    from acp.schema import (
        PermissionOption,
        RequestPermissionRequest,
        ToolCallUpdate,
    )

    return RequestPermissionRequest(
        session_id="sid",
        tool_call=ToolCallUpdate(
            tool_call_id=tool_call_id,
            title=title,
            status="pending",
            raw_input={"command": "ls"},
        ),
        options=[
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            PermissionOption(
                option_id="terminate", name="Terminate", kind="reject_always"
            ),
        ],
    )


def _bar_pending(req: Any) -> Any:
    """Build a PendingApproval for action_approval_decide tests.

    Returns ``Any`` so mypy doesn't get tangled in the optional
    typing chain when the same value flows through
    ``ToolCallState.pending_approval`` (``PendingApproval | None``).
    """
    import asyncio

    from inspect_ai.agent._acp.tui.state import PendingApproval

    return PendingApproval(request=req, event=asyncio.Event())


@skip_if_trio
@pytest.mark.anyio
async def test_pressing_a_resolves_approve_via_screen_binding(
    sample_rows: list[SessionRow],
) -> None:
    """Pressing bare ``a`` while approval is pending fires the screen binding.

    Pins the live-use regression where the bar appeared, the first
    action got mounted, but pressing ``a`` did nothing until the
    operator clicked into the bar — symptom of either focus
    stranded on the now-hidden composer ``TextArea`` (which would
    eat the keystroke) or the action mount sequence racing with
    ``first.focus()`` so the screen's ``priority=True`` binding
    didn't reach ``check_action`` cleanly.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Reproduce live use: the composer TextArea has focus when the
        # approval arrives (typical case — operator was typing or just
        # finished a message). The TextArea gets hidden when lifecycle
        # flips to ``approval``, but Textual's focus might stay
        # stranded on it.
        composer = app.screen.query_one("#composer", TextArea)
        composer.focus()
        await pilot.pause()
        assert app.screen.focused is composer

        pending = _bar_pending(_bar_pending_request("tc-1"))
        app.screen.state.consume_approval_request(pending)
        await pilot.pause()

        # Press the bare letter — no click first.
        await pilot.press("a")
        await pilot.pause()

        tc = app.screen.state._tool_calls_by_id["tc-1"]
        assert tc.pending_approval is None, (
            f"Expected `a` keystroke to resolve the pending approval; "
            f"instead it's still pending. focused={app.screen.focused!r}, "
            f"composer.display={composer.display!r}, "
            f"composer.text={composer.text!r}"
        )
        assert tc.last_approval_decision == "approved"


@skip_if_trio
@pytest.mark.anyio
async def test_action_approval_decide_resolves_pending_approval(
    sample_rows: list[SessionRow],
) -> None:
    """Bare ``a`` (action_approval_decide('approve')) routes through state.resolve_approval."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        pending = _bar_pending(_bar_pending_request("tc-1"))
        app.screen.state.consume_approval_request(pending)
        await pilot.pause()
        assert app.screen.state.lifecycle == "approval"

        app.screen.action_approval_decide("approve")
        await pilot.pause()

        tc = app.screen.state._tool_calls_by_id["tc-1"]
        assert tc.pending_approval is None
        assert tc.last_approval_decision == "approved"
        assert pending.event.is_set()
        assert pending.chosen_option_id == "approve"


@skip_if_trio
@pytest.mark.anyio
async def test_action_approval_decide_noop_outside_approval_lifecycle(
    sample_rows: list[SessionRow],
) -> None:
    """Belt-and-braces: action_approval_decide is a no-op when no approval is pending.

    ``check_action`` already gates the binding so it never fires
    outside ``approval`` lifecycle — but the action itself
    re-checks defensively so a direct call (test / future caller)
    can't accidentally resolve nothing.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        # No pending approval → lifecycle is not "approval".
        assert app.screen.state.lifecycle != "approval"

        # Should not raise; should not mutate any state.
        app.screen.action_approval_decide("approve")
        await pilot.pause()

        assert app.screen.state._tool_calls_by_id == {}


@skip_if_trio
@pytest.mark.anyio
async def test_action_approval_decide_noop_when_option_not_in_request(
    sample_rows: list[SessionRow],
) -> None:
    """``human_approver(choices=[...])`` can omit options — pressing them is a no-op.

    Example: a request configured with only ``approve`` / ``reject``
    doesn't accept ``terminate``. Pressing ``t`` in that case
    should NOT silently resolve as approved or denied — it should
    do nothing so the operator can press a real option.
    """
    from acp.schema import (
        PermissionOption,
        RequestPermissionRequest,
        ToolCallUpdate,
    )

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Request with only approve + reject — no terminate.
        req = RequestPermissionRequest(
            session_id="sid",
            tool_call=ToolCallUpdate(tool_call_id="tc-1", title="ls", status="pending"),
            options=[
                PermissionOption(
                    option_id="approve", name="Approve", kind="allow_once"
                ),
                PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            ],
        )
        pending = _bar_pending(req)
        app.screen.state.consume_approval_request(pending)
        await pilot.pause()

        app.screen.action_approval_decide("terminate")
        await pilot.pause()

        # Pending unchanged — the decision didn't land.
        assert not pending.event.is_set()
        tc = app.screen.state._tool_calls_by_id["tc-1"]
        assert tc.pending_approval is pending
        assert tc.last_approval_decision is None


@skip_if_trio
@pytest.mark.anyio
async def test_check_action_gates_prompt_letter_outside_approval(
    sample_rows: list[SessionRow],
) -> None:
    """``check_action('prompt_letter', ...)`` returns False outside approval mode.

    The approval bar's bare-letter shortcuts (``a`` / ``r`` / ``e`` /
    ``t`` / ``m``) are registered through the shared ``prompt_letter``
    dispatcher so they share Textual's binding table with the cancel
    bar's ``s`` / ``e``. Without the gate, typing ``r`` into the
    composer would fire the reject action instead of inserting the
    letter.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # No approval pending → gate must close.
        assert app.screen.check_action("prompt_letter", ("a",)) is False

        # Approval pending → gate opens.
        app.screen.state.consume_approval_request(
            _bar_pending(_bar_pending_request("tc-1"))
        )
        await pilot.pause()
        assert app.screen.check_action("prompt_letter", ("a",)) is True


@skip_if_trio
@pytest.mark.anyio
async def test_composer_row_hidden_while_approval_card_mounted(
    sample_rows: list[SessionRow],
) -> None:
    """``_apply_lifecycle`` hides ``#composer-row`` so the approval card takes the slot.

    Phase 6b moved approval / cancel from composer-row bars to
    inline cards below the plan strip; the composer row (``>``
    prompt + TextArea) is the entire slot that yields to the
    cards. We hide the ROW rather than just the inner TextArea
    so the ``>`` prompt static doesn't sit orphaned next to a
    blank rectangle.

    Asserts the row hides while a pending approval is parked.
    Doesn't pin a post-resolve visibility state because the
    sample's lifecycle (idle / running / complete) after
    ``resolve_approval`` depends on activity the fake client
    doesn't emit — and ``complete`` / ``scoring`` lifecycles
    independently hide the row. The PR's
    :meth:`_request_card_mounted` helper is exercised by the
    paired submit / newline guard tests below.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer_row = app.screen.query_one("#composer-row")
        # Default: visible (no card mounted, lifecycle still pre-complete).
        assert composer_row.display

        # Pending approval → hidden (card mounted).
        app.screen.state.consume_approval_request(
            _bar_pending(_bar_pending_request("tc-1"))
        )
        await pilot.pause()
        assert not composer_row.display


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_noop_during_approval_with_stranded_focus(
    sample_rows: list[SessionRow],
) -> None:
    """Enter must not ship the hidden composer's draft while approval is pending.

    Pinned regression: the composer TextArea is ``display: none`` during
    approval but its ``text`` is intact. With focus on a non-approval
    widget (transcript, plan strip, or stranded on the now-hidden
    TextArea itself), Enter's ``priority=True`` binding would otherwise
    drop into the composer-submit path and send the invisible draft
    to the agent while the agent is parked awaiting permission.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Seed a draft, then enter approval lifecycle.
        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "draft that must NOT ship"
        app.screen.state.consume_approval_request(
            _bar_pending(_bar_pending_request("tc-1"))
        )
        await pilot.pause()
        # Force focus onto the screen itself (not the bar's action) so
        # the action-press delegation path doesn't apply.
        app.screen.focus()
        await pilot.pause()

        await app.screen.action_submit()
        await pilot.pause()

        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == [], (
            f"Composer text was shipped while approval was pending: {conn.requests}"
        )
        # Draft preserved (not cleared by a stray submit).
        assert composer.text == "draft that must NOT ship"


@skip_if_trio
@pytest.mark.anyio
async def test_action_newline_noop_during_approval(
    sample_rows: list[SessionRow],
) -> None:
    r"""⇧↵ must not smuggle a literal newline into the hidden composer.

    Pinned regression: the TextArea is hidden during approval but its
    ``text`` survives. Without a lifecycle guard, ⇧↵ (``priority=True``)
    would insert ``\n`` into the invisible draft, which would then
    ship on the next non-approval submit.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "draft"
        composer.move_cursor((0, len(composer.text)))
        app.screen.state.consume_approval_request(
            _bar_pending(_bar_pending_request("tc-1"))
        )
        await pilot.pause()

        app.screen.action_newline()
        await pilot.pause()

        assert composer.text == "draft", (
            f"Expected newline insertion to be a no-op in approval lifecycle; "
            f"composer.text={composer.text!r}"
        )


def _seed_pending_elicitation(state: Any) -> None:
    """Park a minimal elicitation on the session state.

    Mirrors what the wire handler does when ``elicitation/create``
    lands: it builds a :class:`PendingElicitation` and calls
    :meth:`SessionState.consume_elicitation_request`. Tests use this
    helper to drive the same code path without standing up the full
    ACP wire.
    """
    import asyncio

    from acp.schema import (
        ElicitationSchema,
        ElicitationStringPropertySchema,
    )

    from inspect_ai.agent._acp.tui.state import PendingElicitation

    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(type="string", title="Name"),
        },
        required=["name"],
    )
    pending = PendingElicitation(
        message="What's your name?",
        requested_schema=schema,
        event=asyncio.Event(),
    )
    state.consume_elicitation_request(pending)


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_noop_while_elicitation_card_mounted(
    sample_rows: list[SessionRow],
) -> None:
    """Enter must not ship the hidden composer's draft while elicitation is parked.

    Pinned regression: elicitation does NOT change
    ``SessionState.lifecycle`` (the agent is parked in
    ``elicitation/create`` but the lifecycle stays ``running`` /
    ``idle``). Earlier the submit guard only knew about the cancel
    card and the approval lifecycle, so a stray ↵ landing on a
    non-form-focus widget while the elicitation card was mounted
    would still ``session/prompt`` the invisible draft. The
    :meth:`_request_card_mounted` predicate is the fix — same
    helper drives ``hide_composer_row`` so the visible/sendable
    states can't drift.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "draft that must NOT ship"
        _seed_pending_elicitation(app.screen.state)
        await pilot.pause()
        # Strand focus on the screen so the card's form-input
        # delegation doesn't apply.
        app.screen.focus()
        await pilot.pause()

        await app.screen.action_submit()
        await pilot.pause()

        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == [], (
            f"Composer text was shipped while elicitation was pending: {conn.requests}"
        )
        assert composer.text == "draft that must NOT ship"


@skip_if_trio
@pytest.mark.anyio
async def test_action_newline_noop_while_elicitation_card_mounted(
    sample_rows: list[SessionRow],
) -> None:
    r"""⇧↵ must not smuggle a literal newline into the hidden composer.

    Companion to
    :func:`test_action_submit_noop_while_elicitation_card_mounted` for
    the newline path — same gap (lifecycle doesn't change for
    elicitation), same fix (single ``_request_card_mounted``
    helper).
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        composer = app.screen.query_one("#composer", TextArea)
        composer.text = "draft"
        composer.move_cursor((0, len(composer.text)))
        _seed_pending_elicitation(app.screen.state)
        await pilot.pause()

        app.screen.action_newline()
        await pilot.pause()

        assert composer.text == "draft", (
            f"Expected newline to be a no-op while elicitation card was mounted; "
            f"composer.text={composer.text!r}"
        )


@skip_if_trio
@pytest.mark.anyio
async def test_escape_with_elicitation_card_mounted_declines(
    sample_rows: list[SessionRow],
) -> None:
    """Esc on a mounted elicitation card declines it.

    Mirrors the cancel-card precedence in
    :meth:`SessionScreen.action_interrupt`: the elicitation
    takeover is the *highest* priority branch so Esc reads as
    "back out of this prompt" the same way it does for cancel.
    Bringing parity with approval / cancel cards (whose Esc
    behaviour the user reported missing for elicitation).

    Asserts the resolution path runs end-to-end: the screen's
    ``on_elicitation_decision_requested`` handler receives the
    bubbled :class:`ElicitationDecisionRequested` (action=decline),
    calls :meth:`SessionState.resolve_elicitation`, and the
    pending event fires so the parked JSON-RPC handler unblocks.
    The card unmounts as a consequence — assert that too.
    """
    from inspect_ai.agent._acp.tui.widgets.elicitation_card import _ElicitationCard

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Seed an elicitation; let the apply-loop mount the card.
        _seed_pending_elicitation(app.screen.state)
        await pilot.pause()
        # call_after_refresh in the card's on_mount defers focus
        # by one refresh — pump another pause so focus has landed
        # before Esc fires.
        await pilot.pause()
        # Snapshot the pending event so we can check it fired.
        pending = app.screen.state.pending_elicitation
        assert pending is not None
        # Card mounted.
        assert len(app.screen.query(_ElicitationCard)) == 1

        # Press Esc → action_interrupt's elicitation precedence
        # branch posts a decline message; the screen handler
        # resolves and the apply-loop unmounts the card.
        await pilot.press("escape")
        # The decline bubble travels card → screen handler →
        # resolve_elicitation → pending.event.set(). Pump enough
        # pauses for the message + the subsequent re-apply tick.
        for _ in range(5):
            await pilot.pause()

        # State cleared, pending event fired, card unmounted.
        assert app.screen.state.pending_elicitation is None
        assert pending.action == "decline"
        assert pending.event.is_set()
        assert list(app.screen.query(_ElicitationCard)) == []


@skip_if_trio
@pytest.mark.anyio
async def test_escape_while_cancel_rpc_in_flight_does_not_clear_pending(
    sample_rows: list[SessionRow],
) -> None:
    """Race regression: Esc while ``inspect/cancel_sample`` is in flight is a no-op.

    Pins the session-screen half of the cancel-in-flight guard
    pair (the card half is covered by
    ``test_back_after_score_in_flight_does_not_clear_pending`` in
    ``test_cancel_card.py``). Once the card flips ``_resolved``
    to True the screen's :meth:`action_interrupt` must NOT call
    ``state.resolve_cancel`` — doing so would unmount the card
    underneath the in-flight worker and the UI would lie about
    "keep running" while the RPC could still succeed.
    """
    import anyio

    from inspect_ai.agent._acp.tui.state import PendingCancel
    from inspect_ai.agent._acp.tui.widgets.cancel_card import _CancelCard

    class _SlowConnection:
        def __init__(self) -> None:
            self.release = anyio.Event()
            self.calls: list[tuple[str, Any]] = []

        async def send_request(self, method: str, params: Any) -> Any:
            self.calls.append((method, params))
            await self.release.wait()
            return None

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        slow = _SlowConnection()
        pending = PendingCancel(
            fails_on_error=False, connection=slow, session_id="sess-x"
        )
        app.screen.state.consume_cancel_request(pending)
        for _ in range(5):
            await pilot.pause()
            cards = list(app.screen.query(_CancelCard))
            if cards:
                break
        cards = list(app.screen.query(_CancelCard))
        assert len(cards) == 1
        card = cards[0]

        # Drive the card into the in-flight state — worker parks
        # inside the slow connection's send_request.
        card.choose("score")
        for _ in range(5):
            await pilot.pause()
            if slow.calls:
                break
        assert card._resolved is True
        assert slow.calls, "score did not fire send_request"
        assert app.screen.state.pending_cancel is pending

        # Esc routes through action_interrupt → cancel-card
        # precedence → ``card._resolved`` short-circuit. Must NOT
        # clear pending.
        await app.screen.action_interrupt()
        await pilot.pause()
        assert app.screen.state.pending_cancel is pending, (
            "Esc must not clear pending_cancel while cancel RPC is in flight"
        )

        # Let the worker finish so the test exits cleanly (without
        # this the worker would still be parked when the App tears
        # down and Textual logs a warning).
        slow.release.set()
        for _ in range(10):
            await pilot.pause()
            if app.screen.state.pending_cancel is None:
                break
        assert app.screen.state.pending_cancel is None


@skip_if_trio
@pytest.mark.anyio
async def test_escape_with_both_cards_mounted_dismisses_cancel_first(
    sample_rows: list[SessionRow],
) -> None:
    """Esc precedence when elicitation AND cancel are both parked.

    Pinned regression: ^N stays available while an elicitation is
    pending, so the operator can have BOTH cards mounted at once.
    Earlier the elicitation branch ran first in
    :meth:`action_interrupt` and Esc declined the agent's earlier
    question instead of backing out of the cancel prompt — wrong
    on two counts: it shipped an unintended decline over the wire
    AND left the cancel card up looking like Esc did nothing.

    New order: cancel beats elicitation. Cancel is the *more
    recent* operator decision (^N landed after the question was
    already mounted), so the first Esc backs out of cancel; a
    second Esc then declines the elicitation if the operator
    still wants.
    """
    from inspect_ai.agent._acp.tui.state import PendingCancel
    from inspect_ai.agent._acp.tui.widgets.cancel_card import _CancelCard
    from inspect_ai.agent._acp.tui.widgets.elicitation_card import _ElicitationCard

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Park the elicitation first (the agent asked a question
        # and is now blocked).
        _seed_pending_elicitation(app.screen.state)
        for _ in range(5):
            await pilot.pause()
            if list(app.screen.query(_ElicitationCard)):
                break
        elicitation_pending = app.screen.state.pending_elicitation
        assert elicitation_pending is not None

        # Now the operator presses ^N — cancel card mounts on top
        # of the elicitation card. Park a PendingCancel directly
        # rather than driving the binding, so the test stays
        # focused on the Esc precedence and not on cancel-sample's
        # own dispatch.
        cancel_pending = PendingCancel(
            fails_on_error=False, connection=MagicMock(), session_id="sess-x"
        )
        app.screen.state.consume_cancel_request(cancel_pending)
        for _ in range(5):
            await pilot.pause()
            if list(app.screen.query(_CancelCard)):
                break

        # Both cards are mounted now.
        assert list(app.screen.query(_CancelCard)), "cancel card not mounted"
        assert list(app.screen.query(_ElicitationCard)), "elicitation card not mounted"

        # First Esc → backs out of cancel, leaves elicitation
        # intact (no decline shipped).
        await app.screen.action_interrupt()
        await pilot.pause()
        assert app.screen.state.pending_cancel is None
        assert app.screen.state.pending_elicitation is elicitation_pending
        assert elicitation_pending.action is None, (
            "elicitation must NOT be declined while cancel takes the Esc"
        )
        assert not elicitation_pending.event.is_set()
        # Cancel card gone, elicitation card still up.
        assert list(app.screen.query(_CancelCard)) == []
        assert list(app.screen.query(_ElicitationCard))

        # Second Esc → now declines the elicitation (the only
        # remaining card). Positive proof that the elicitation
        # branch still fires once cancel is out of the way.
        await app.screen.action_interrupt()
        for _ in range(5):
            await pilot.pause()
            if app.screen.state.pending_elicitation is None:
                break
        assert app.screen.state.pending_elicitation is None
        assert elicitation_pending.action == "decline"
        assert elicitation_pending.event.is_set()
        assert list(app.screen.query(_ElicitationCard)) == []
