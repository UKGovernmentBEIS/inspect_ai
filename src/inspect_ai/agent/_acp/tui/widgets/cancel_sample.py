"""Composer-area cancel-sample bar.

When the operator hits ``^N`` on the session screen, this bar takes
over the composer row (the ``Input`` and the :class:`_ApprovalBar`
both hide) and presents a terminal-prompt-styled choice:

    > cancel sample?   [ s ] Cancel: Score   [ e ] Cancel: Error   [ esc ] Go Back

The bracketed underlined letter on each option doubles as the
single-key shortcut (handled by ``SessionScreen``'s bindings — the
bar's option widgets are clickable and Tab-navigable, the screen's
``s`` / ``e`` bindings dispatch to the same handler when the cancel
bar is visible).

The ``Cancel: Error`` option is gated on the sample's server-side
``fails_on_error`` flag (read from :attr:`SessionRow.fails_on_error`
which the picker propagates via the ``failsOnError`` ``_meta`` field).
When ``fails_on_error=True`` the operator-triggered error action is
moot — the sample would error on its own — so the bar only offers
``Cancel: Score`` and ``Go Back``.

The bar mirrors :class:`_ApprovalBar`'s composer-area pattern (same
``_PromptOption`` widgets, same focus-on-show behaviour) so the
operator's muscle memory carries over between the two prompts. Unlike
the approval bar, it does NOT subscribe to :class:`SessionState`:
visibility is controlled imperatively by :class:`SessionScreen`
via :meth:`show` and :meth:`hide` because the trigger is a keystroke,
not a wire event.
"""

from __future__ import annotations

from typing import Any, Literal

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai.agent._acp.inspect_ext import INSPECT_CANCEL_SAMPLE_METHOD

from ._prompt import _PromptOption

# ID prefix for the focusable option widgets so the bar can find them
# via query + so id-based tests can target them.
_BUTTON_ID_PREFIX = "cancel-sample-opt-"


_CancelChoice = Literal["score", "error", "back"]


class _CancelSampleBar(Widget):
    """Composer-area bar for confirming an operator-initiated sample cancel.

    Hidden by default. :class:`SessionScreen` calls :meth:`show` on
    ``^N`` (passing the bound session's row + connection + session id)
    to bring it up, and :meth:`hide` to dismiss it.

    The bar owns the JSON-RPC plumbing — when the operator picks a
    disposition, it fires ``inspect/cancel_sample`` directly on the
    bound connection and then hides itself. The natural
    ``inspect/session_ended`` → :meth:`SessionState.mark_complete`
    flow handles the UI transition; the bar doesn't need to wait for
    that signal to dismiss.
    """

    DEFAULT_CSS = """
    _CancelSampleBar {
        layout: horizontal;
        height: 1;
        width: 1fr;
    }
    _CancelSampleBar.-hidden { display: none; }
    /* Question label sits left of the options; muted grey so the
     * eye lands on the choices. Mirrors the approval bar. */
    _CancelSampleBar #cancel-question {
        width: auto;
        color: $foreground 55%;
        padding-right: 2;
    }
    /* Per-kind option colours — the option widget itself stays
     * colour-neutral and the bar layers the vocabulary on top via
     * the ``kind-…`` class the option attaches. ``score`` reads as
     * a benign / positive outcome (green), ``error`` reads as a
     * destructive choice (warning), and ``back`` is dim so the eye
     * doesn't drift to the bail-out as a primary action. */
    _CancelSampleBar _PromptOption.kind-score { color: $success; }
    _CancelSampleBar _PromptOption.kind-error { color: $warning; }
    _CancelSampleBar _PromptOption.kind-back { color: $foreground 55%; }
    """

    def __init__(self) -> None:
        super().__init__()
        # Snapshot of the active cancel context — populated by ``show``,
        # cleared by ``hide``. ``None`` while the bar is hidden.
        self._row_fails_on_error: bool = False
        self._connection: Any = None
        self._session_id: str | None = None
        # Idempotence guard — Enter mash on a focused option could
        # otherwise fire the request twice before the hide races.
        self._resolved = False

    def compose(self) -> ComposeResult:
        yield Static("cancel sample?", id="cancel-question", markup=False)
        # Options mount dynamically via ``_mount_options`` on each
        # ``show`` call — the set depends on the row's
        # ``fails_on_error`` flag.

    def on_mount(self) -> None:
        # Start hidden — ``show`` flips us visible when the operator
        # invokes ``^N``.
        self.add_class("-hidden")

    @property
    def is_visible(self) -> bool:
        """Whether the bar is currently shown over the composer row."""
        return "-hidden" not in self.classes

    def show(
        self,
        *,
        fails_on_error: bool,
        connection: Any,
        session_id: str,
    ) -> None:
        """Make the bar visible and mount the options for this session.

        Idempotent for a re-show with the same parameters: clears any
        previous options first so a stale ``error`` button can't linger
        from a prior show that targeted a different row. The first
        option (``score``) is focused so Enter activates it without
        a Tab.
        """
        self._row_fails_on_error = fails_on_error
        self._connection = connection
        self._session_id = session_id
        self._resolved = False
        self._clear_options()
        self._mount_options(fails_on_error)
        self.remove_class("-hidden")
        # Focus the score option so Enter activates it without a Tab.
        first = self.query(_PromptOption).first()
        if first is not None:
            first.focus()

    def hide(self) -> None:
        """Re-hide the bar and clear its mounted options + session context."""
        self.add_class("-hidden")
        self._clear_options()
        self._connection = None
        self._session_id = None

    def _clear_options(self) -> None:
        for child in list(self.query(_PromptOption)):
            child.remove()

    def _mount_options(self, fails_on_error: bool) -> None:
        # ``score`` is always offered; ``error`` only when the sample
        # isn't already configured to fail on errors (otherwise the
        # operator's manual error just races with the auto-fail).
        # ``back`` lets the operator bail without committing.
        self.mount(
            _PromptOption(
                action_id="score",
                key="s",
                label="Cancel: Score",
                kind="score",
                widget_id=f"{_BUTTON_ID_PREFIX}score",
            )
        )
        if not fails_on_error:
            self.mount(
                _PromptOption(
                    action_id="error",
                    key="e",
                    label="Cancel: Error",
                    kind="error",
                    widget_id=f"{_BUTTON_ID_PREFIX}error",
                )
            )
        self.mount(
            _PromptOption(
                action_id="back",
                key="esc",
                label="Go Back",
                kind="back",
                widget_id=f"{_BUTTON_ID_PREFIX}back",
            )
        )

    def choose(self, action: _CancelChoice) -> None:
        """Activate one of the cancel choices — the bare-letter entry point.

        :class:`SessionScreen` calls this from its ``s`` / ``e``
        bindings (gated on :attr:`is_visible`) so a single code path
        drives both keyboard shortcuts and option clicks.
        """
        if action == "back":
            self.hide()
            return
        if action == "error" and self._row_fails_on_error:
            # Defence-in-depth: the screen's ``check_action`` gate
            # should already have hidden the ``e`` binding when
            # ``fails_on_error`` is True, but the bar stays robust if
            # a future framework change exposes it.
            return
        if self._resolved:
            return
        if self._connection is None or self._session_id is None:
            # Show was never called or hide already ran — drop silently.
            return
        self._resolved = True
        # Capture connection + session id BEFORE hiding — ``hide`` clears
        # both slots, and the worker coroutine runs on a later tick so
        # it would otherwise observe the cleared state and silently
        # drop the request.
        connection = self._connection
        session_id = self._session_id
        # Kick the request off in a worker so the bar can hide
        # immediately; failures surface via toast and the natural
        # session_ended flow drives the lifecycle transition.
        self.run_worker(
            self._fire_cancel(connection, session_id, action),
            name="cancel-sample",
            exclusive=True,
        )
        self.hide()

    def on_prompt_option_pressed(self, event: _PromptOption.Pressed) -> None:
        """Route an option press (click or Enter / Space) through :meth:`choose`."""
        event.stop()
        # The action_id strings are exactly the choose() literals.
        self.choose(event.action_id)  # type: ignore[arg-type]

    async def _fire_cancel(
        self,
        connection: Any,
        session_id: str,
        action: Literal["score", "error"],
    ) -> None:
        """Send ``inspect/cancel_sample`` and surface any failure as a toast.

        Connection + session id are passed in by :meth:`choose` so the
        worker doesn't race with :meth:`hide` clearing the slots. On
        the happy path the server fires ``inspect/session_ended``
        which the client already wires to ``mark_complete`` (in
        :func:`attach_session`), flipping the SessionScreen's
        lifecycle to ``complete``. On error (sample already gone,
        server rejected the action) we notify and stay hidden — the
        operator's intent was "I'm done with this sample" and
        re-presenting the bar would be confusing.
        """
        try:
            await connection.send_request(
                INSPECT_CANCEL_SAMPLE_METHOD,
                {"sessionId": session_id, "action": action},
            )
        except Exception as exc:
            self.app.notify(f"cancel failed: {exc}", severity="error")
