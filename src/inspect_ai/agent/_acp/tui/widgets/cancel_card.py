"""Inline cancel-sample card.

Rendered into the session screen while
:attr:`~inspect_ai.agent._acp.tui.state.SessionState.pending_cancel`
is set; unmounts as soon as the operator picks Back / Score / Error
or the sample terminates by other means. Replaces the composer-row
:class:`_CancelSampleBar` from Phase 6a — the cancel-sample prompt
now lives inline below the transcript, alongside the elicitation
and approval cards, sharing the :class:`InlineRequestCard`
primitive.

Cancel is the only one of the three card surfaces where the agent
keeps running while the operator deliberates. The card mounts in
the composer's slot (below the plan strip, above the footer) so it
is always on screen regardless of where the operator has scrolled
the transcript — no auto-follow / scroll-anchoring is needed.

Action shortcuts: the screen registers ``s`` / ``e`` / ``esc``
bindings as today; the buttons here carry the
``cancel-sample-opt-<choice>`` id convention from the old
:class:`_CancelSampleBar`, so the screen's existing id-based
delegation in ``action_cancel_choice`` continues to dispatch to
them.
"""

from __future__ import annotations

from typing import Any, Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Button, Static

from inspect_ai.agent._acp.inspect_ext import INSPECT_CANCEL_SAMPLE_METHOD
from inspect_ai.agent._acp.tui.state import PendingCancel, SessionState

from .inline_request_card import InlineRequestCard

# ID prefix for the focusable cancel-option buttons. Preserved from
# the old composer-row bar so the session screen's id-based
# delegation works unchanged.
_BUTTON_ID_PREFIX = "cancel-sample-opt-"

_CancelChoice = Literal["score", "error", "back"]


_LABELS: dict[_CancelChoice, str] = {
    "score": "Cancel: Score",
    "error": "Cancel: Error",
    "back": "Go Back",
}

# Underlined-letter shortcut hint for each choice. The actual key
# binding lives on :class:`SessionScreen`; this just paints the cue.
_SHORTCUT: dict[_CancelChoice, str] = {
    "score": "s",
    "error": "e",
    # Display form for the Escape key. Case matters here — this
    # string is rendered verbatim in the button label, not used as
    # a binding key (those live on the screen).
    "back": "Esc",
}


def _button_label(choice: _CancelChoice) -> Text:
    """Render ``Score`` / ``Error`` / ``Back`` with the shortcut letter underlined.

    Mirrors the look of the old ``_PromptOption`` (``[ s ] Cancel:
    Score``), translated to a compact Button label. For
    single-letter shortcuts we find the action-bearing letter
    inside the label (case-insensitive) and underline it in place
    — e.g. ``Cancel: <u>S</u>core``. For multi-char shortcuts
    (``Esc``) the cue isn't a letter inside the label, so we
    append it parenthetically: ``Go Back (Esc)``.
    """
    label = _LABELS[choice]
    shortcut = _SHORTCUT[choice]
    text = Text()
    if len(shortcut) == 1:
        # Look for the shortcut letter inside the label so we can
        # underline it in place. We search the *upper-case* form
        # first because the action-bearing letter is invariably
        # capitalised in our labels (``Score`` / ``Error``), and
        # the lowercase ``c`` in ``Cancel:`` would otherwise win
        # the search for shortcut ``c``.
        idx = label.find(shortcut.upper())
        if idx < 0:
            idx = label.lower().find(shortcut.lower())
        if idx >= 0:
            text.append(label[:idx])
            text.append(label[idx], style="underline")
            text.append(label[idx + 1 :])
        else:
            text.append(label)
            text.append(f" ({shortcut.upper()})")
    else:
        text.append(label)
        text.append(f" ({shortcut})")
    return text


class _CancelCard(InlineRequestCard):
    """Inline card rendered while a ``^N``-initiated cancel is pending.

    Header is the one-line prompt; no body. Actions are three
    compact buttons: Score (blue / primary — the safe disposition
    that proceeds to scoring), Error (warning, gated on
    ``fails_on_error`` — the destructive disposition), Back (dim).

    Owns the ``inspect/cancel_sample`` RPC plumbing — when the
    operator picks Score / Error, the card fires the RPC on a
    Textual worker and then resolves the pending. On success it
    also calls :meth:`SessionState.mark_sample_cancelling` so the
    in-flight chrome (spinning chip, ticking timer, pending
    approvals) flips terminal immediately; the natural
    ``inspect/session_ended`` flow handles the lifecycle transition.
    On failure, the operator gets an error toast and local state is
    left honest.
    """

    DEFAULT_CSS = """
    /* Cancel-specific kind vocabulary. ``kind-score`` is the
     * "cancel cleanly, proceed to scoring" disposition — we paint
     * it with ``$primary`` (the same blue Submit on the
     * elicitation card uses) so the operator's eye lands on the
     * safe choice. ``kind-error`` is the destructive disposition
     * (cancel as an error, no scoring) — ``$warning`` is the
     * orange-ish "this ends the run" cue, matching the
     * ``kind-reject-once`` colour the approval card uses. ``back``
     * is left default so the dismiss action doesn't compete for
     * attention. */
    _CancelCard #request-actions Button.kind-score {
        color: $primary;
    }
    _CancelCard #request-actions Button.kind-error {
        color: $warning;
    }
    """

    def __init__(self, pending: PendingCancel, state: SessionState) -> None:
        super().__init__()
        self.request = pending
        self._pending = pending
        self._state = state
        # Idempotence guard — Enter mash on a focused button could
        # otherwise fire the RPC twice before the unmount races.
        self._resolved = False

    @classmethod
    def from_pending(cls, pending: PendingCancel, state: SessionState) -> "_CancelCard":
        """Build a card for a parked :class:`PendingCancel`."""
        return cls(pending, state)

    @property
    def header_text(self) -> str:
        return "Cancel the sample?"

    def compose_body(self) -> ComposeResult:
        # No body — the header reads as the prompt and the buttons
        # carry the dispositions. Matches the bar shape it replaces.
        return
        yield  # pragma: no cover — make this a generator function

    def compose_actions(self) -> ComposeResult:
        # Score is always offered.
        yield Button(
            _button_label("score"),
            id=f"{_BUTTON_ID_PREFIX}score",
            compact=True,
            classes="kind-score",
            tooltip="Cancel the sample and proceed to scoring.",
        )
        # Error only when the sample isn't already configured to
        # fail on errors (otherwise the operator's manual error just
        # races with the auto-fail).
        if not self._pending.fails_on_error:
            yield Button(
                _button_label("error"),
                id=f"{_BUTTON_ID_PREFIX}error",
                compact=True,
                classes="kind-error",
                tooltip="Cancel the sample as an error (no scoring).",
            )
        yield Button(
            _button_label("back"),
            id=f"{_BUTTON_ID_PREFIX}back",
            compact=True,
            classes="kind-back",
            tooltip="Dismiss this prompt; keep the sample running.",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Stop here so the screen doesn't see a raw Button.Pressed —
        # the card itself owns the disposition handling.
        event.stop()
        button_id = event.button.id or ""
        if not button_id.startswith(_BUTTON_ID_PREFIX):
            return
        choice_str = button_id[len(_BUTTON_ID_PREFIX) :]
        if choice_str not in ("score", "error", "back"):
            return
        # Narrow to the literal type for the dispatch helper.
        choice: _CancelChoice = choice_str  # type: ignore[assignment]
        self.choose(choice)

    def choose(self, choice: _CancelChoice) -> None:
        """Activate one of the cancel choices — the bare-letter entry point.

        :class:`SessionScreen` calls this from its ``s`` / ``e`` /
        ``esc`` bindings so a single code path drives both keyboard
        shortcuts and option clicks.

        Once Score/Error has fired (``_resolved=True``) ALL further
        choices — including Back — are ignored: the
        ``inspect/cancel_sample`` RPC is in flight and clearing
        ``pending_cancel`` underneath it would unmount the card
        while the cancel still proceeds, leaving the UI saying
        "keep running" while the sample actually ends. The
        in-flight feedback comes from :meth:`_enter_cancelling`
        (header → ``"Cancelling…"``, action buttons disabled);
        Esc routes through :meth:`SessionScreen.action_interrupt`
        which mirrors the same ``_resolved`` no-op.
        """
        if self._resolved:
            return
        if choice == "back":
            self._state.resolve_cancel()
            return
        if choice == "error" and self._pending.fails_on_error:
            # Defence-in-depth: the screen's ``check_action`` gate
            # should already have hidden the ``e`` binding when
            # ``fails_on_error`` is True, but stay robust if a future
            # framework change exposes it.
            return
        self._resolved = True
        self._enter_cancelling()
        # Capture context BEFORE the worker starts — the pending may
        # be cleared by ``resolve_cancel`` before the worker runs.
        connection = self._pending.connection
        session_id = self._pending.session_id
        self.run_worker(
            self._fire_cancel(connection, session_id, choice),
            name="cancel-sample",
            exclusive=True,
        )

    def _enter_cancelling(self) -> None:
        """Flip the card into "cancel in flight" presentation.

        Header → ``"Cancelling…"`` so the operator sees their
        choice acknowledged immediately, and every action button
        is disabled so a follow-up click on Back / Score / Error
        can't fire a second time. ``_resolved`` is the load-bearing
        guard against the race — the disabled buttons are belt-
        and-braces visual reinforcement, since a focused button +
        Enter mash, a transcript Tab cycle landing on a stale
        button, or the screen's bare-letter dispatch could all
        otherwise re-enter :meth:`choose` between the worker
        starting and the natural unmount.
        """
        try:
            header = self.query_one(".request-header", Static)
            header.update("Cancelling…")
        except Exception:  # pragma: no cover — defensive
            # Header lookup shouldn't fail in practice (compose
            # mounts it before the operator can press a button),
            # but stay robust if a future refactor changes the
            # selector — the disabled-button guard below is still
            # the load-bearing user-facing protection.
            pass
        for button in self.query(Button):
            button.disabled = True

    async def _fire_cancel(
        self,
        connection: Any,
        session_id: str,
        choice: Literal["score", "error"],
    ) -> None:
        """Send ``inspect/cancel_sample``; flip state only on success.

        On success: call :meth:`SessionState.mark_sample_cancelling`
        so the in-flight chrome flips terminal immediately, then
        clear the pending. On failure: toast the operator and clear
        the pending — local state stays honest (the sample didn't
        actually cancel).
        """
        try:
            await connection.send_request(
                INSPECT_CANCEL_SAMPLE_METHOD,
                {"sessionId": session_id, "action": choice},
            )
        except Exception as exc:
            self.app.notify(f"cancel failed: {exc}", severity="error")
            self._state.resolve_cancel()
            return
        self._state.mark_sample_cancelling()
        self._state.resolve_cancel()
