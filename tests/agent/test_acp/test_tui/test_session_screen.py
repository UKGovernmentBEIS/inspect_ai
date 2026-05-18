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

import pytest
from test_helpers.utils import skip_if_trio
from textual.binding import Binding
from textual.widgets import Input, Static

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
    assert by_key["enter"].priority is True
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

    The single-line ``Input`` doesn't render the newline locally, but
    the character lives in ``Input.value`` and ships on submit. This
    pins the binding so the footer hint matches what the action does.
    """
    by_key = _bindings_by_key()
    assert "shift+enter" in by_key
    assert by_key["shift+enter"].action == "newline"
    assert by_key["shift+enter"].show is True
    assert by_key["shift+enter"].key_display == "⇧↵"
    assert by_key["shift+enter"].priority is True


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
        composer = app.screen.query_one("#composer", Input)
        composer.value = "line one"
        composer.cursor_position = len(composer.value)
        app.screen.action_newline()
        await pilot.pause()
        assert composer.value == "line one\n"
        # And no requests were sent — the newline is composer-local.
        # ``FakeConnection.requests`` records ``(method, params)``
        # tuples, so an empty list is the precise invariant.
        conn = cast(Any, app.screen._session.connection)
        assert conn.requests == []


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
        composer = app.screen.query_one("#composer", Input)
        # Composer must be enabled — Phase 3 makes it interactive.
        assert composer.disabled is False
        composer.value = "  please continue  "
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
        assert composer.value == ""


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
        composer = app.screen.query_one("#composer", Input)
        composer.value = "   "
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
        composer = app.screen.query_one("#composer", Input)
        composer.value = "draft text"
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = cast(Any, app.screen._session.connection)
        assert conn.notifications == []
        assert composer.value == ""


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
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
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
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
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
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
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
        composer = app.screen.query_one("#composer", Input)
        assert "esc to interrupt" in composer.placeholder


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
        composer = app.screen.query_one("#composer", Input)
        assert "esc to interrupt" not in composer.placeholder


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
        composer = app.screen.query_one("#composer", Input)
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
        composer = app.screen.query_one("#composer", Input)
        # Bypass the disabled flag in the test by writing directly to
        # value (an Input.disabled wouldn't block programmatic writes).
        composer.value = "anything"
        await app.screen.action_submit()
        await pilot.pause()
        conn = cast(Any, cast(Any, app.screen)._session.connection)
        assert conn.requests == []
        # And the composer value is preserved — we didn't clear it.
        assert composer.value == "anything"


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
        composer = app.screen.query_one("#composer", Input)
        # Pre-seed a value we can verify wasn't mutated.
        composer.value = "draft"
        composer.cursor_position = len(composer.value)
        app.screen.action_newline()
        await pilot.pause()
        assert composer.value == "draft"
