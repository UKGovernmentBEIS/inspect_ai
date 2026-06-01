"""Session screen for the ``inspect acp`` TUI.

Layout:

  - :class:`SessionHeaderWidget` — single-row app title + meta
    identifiers (task / sample / epoch / agent / tokens) + connection
    indicator.
  - :class:`TranscriptWidget` — scrollable conversation pane.
  - Composer ``TextArea`` — user types prompts; ``↵`` sends, ``⇧↵`` inserts a
    newline, and ``Esc`` interrupts (or clears the draft when one is present).
  - Textual ``Footer`` for keymap hints.

A periodic ``set_interval`` timer calls ``_tick`` so in-flight tool
duration counters and the assistant chip spinner keep ticking even
between notifications.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Static, TextArea

from inspect_ai.agent._acp.inspect_ext import INSPECT_CANCEL_TOOL_CALL_METHOD

from .client import AttachedSession
from .state import PendingCancel, SessionState, _QueuedEnqueueHandle
from .widgets import (
    AppFooter,
    PlanStripWidget,
    SessionHeaderWidget,
    TranscriptWidget,
)
from .widgets.approval_card import _ApprovalCard
from .widgets.cancel_card import _BUTTON_ID_PREFIX as _CANCEL_BUTTON_ID_PREFIX
from .widgets.cancel_card import _CancelCard
from .widgets.elicitation_card import (
    ElicitationDecisionRequested,
    _ElicitationCard,
)
from .widgets.inline_request_card import InlineRequestCard
from .widgets.plan import PlanOverlayScreen
from .widgets.tool_call import _BUTTON_ID_PREFIX, ApprovalDecisionRequested

_STATUS_TICK_SECONDS = 0.5
"""How often time-driven UI bits get nudged.

In-flight tool durations + the assistant chip spinner don't have
state mutations that fire ``subscribe``, so the screen ticks them on
this interval. Sub-second so the motion feels responsive; not so
fast that idle CPU is wasted.
"""


class ComposerTextArea(TextArea):
    r"""TextArea where Enter submits and Ctrl+J inserts a newline.

    This mirrors the native full-display composer: Enter is handled
    inside the focused TextArea instead of through a priority screen
    binding, so terminal-specific Shift+Enter encodings can be
    interpreted before the screen decides to submit.
    """

    class Submitted(Message):
        """Posted when the user presses Enter to submit the message."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            # Heuristic for terminals (e.g. macOS Terminal.app) that
            # emit Shift+Enter as two events: a backslash key followed
            # by a plain Enter. By the time we see Enter the backslash
            # is already in the buffer. If the text ends with a single
            # backslash, treat the sequence as Shift+Enter: strip the
            # backslash and insert a newline instead of submitting.
            # Side-effect: messages that intentionally end with a
            # single ``\`` can't be submitted with Enter — add another
            # character first.
            if self.text.endswith("\\"):
                self.action_delete_left()
                self.insert("\n")
                return
            self.post_message(self.Submitted())
            return
        if event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)


class SessionScreen(Screen[None]):
    """Phase 2 attached-session view."""

    # Enter is deliberately not priority-bound: the focused composer
    # TextArea handles Enter itself so it can apply the same
    # terminal-specific Shift+Enter heuristic as the native full UI.
    # Escape and navigation bindings stay priority-bound so the user
    # can always interrupt or leave the session.
    BINDINGS = [
        Binding("enter", "submit", "submit", show=True, key_display="↵"),
        # ``shift+enter`` inserts a literal ``\n`` into the composer.
        # TextArea's default Enter behavior is also newline, so this
        # priority binding keeps the chat-input convention intact:
        # Enter submits, Shift+Enter creates another line.
        Binding(
            "shift+enter",
            "newline",
            "newline",
            show=True,
            key_display="⇧↵",
            priority=True,
        ),
        # Hidden fallback for terminals that don't reliably report
        # Shift+Enter distinctly. Ctrl+J sends LF and is broadly
        # distinguishable at the terminal-input layer.
        Binding("ctrl+j", "newline", show=False, priority=True),
        Binding("escape", "interrupt", "interrupt", show=True, priority=True),
        # ``^p`` opens the plan overlay; pressing it again (the overlay's
        # own binding takes over there with ``priority=True``) closes it.
        # Ordered after ``interrupt`` and before ``switch sample`` so
        # the footer reads "submit / newline / interrupt / plan / switch".
        # :meth:`check_action` hides the footer hint when the agent
        # hasn't emitted a plan yet, so non-planning sessions see four
        # entries instead of five.
        Binding(
            "ctrl+p",
            "toggle_plan",
            "plan",
            show=True,
            priority=True,
        ),
        # ``^l`` cancels every eligible in-flight tool (per
        # :attr:`SessionState.cancel_tool_call_ids`). Under parallel
        # tool calls a single press fans out to all in-flight siblings.
        # Ordered after ``plan`` and before ``cancel_sample`` so the
        # footer left-group reads "submit / newline / interrupt / plan
        # / cancel tool" with the navigation-cluster (cancel sample /
        # switch / quit) flushed right. This screen-footer binding is
        # the only cancel-tool affordance; affected cards reflect the
        # request after dispatch via their ``cancelling…`` footer
        # marker. :meth:`check_action` hides the hint when no eligible
        # tool is in flight.
        Binding(
            "ctrl+l",
            "cancel_tool_call",
            "cancel tool",
            show=True,
            priority=True,
        ),
        # ``^n`` opens the cancel-sample confirmation modal. Ordered
        # before ``^s switch sample`` so the footer right-cluster reads
        # "cancel / switch / quit" — the three commands that end or
        # navigate away from the current session, grouped together.
        # :meth:`check_action` hides the hint once the lifecycle is
        # ``complete`` (no sample to cancel any more).
        Binding(
            "ctrl+n",
            "cancel_sample",
            "cancel sample",
            show=True,
            priority=True,
        ),
        Binding(
            "ctrl+s",
            "switch_sample",
            "switch sample",
            show=True,
            priority=True,
        ),
        # Bare-letter shortcuts for the two composer-area prompt bars.
        # ``show=False`` for all of them because the bar itself renders
        # the keys inline (``[ a ] approve``, ``[ s ] Cancel: Score``,
        # …); duplicating them in the footer would just add noise.
        #
        # Routing happens through :meth:`action_prompt_letter`, a
        # single dispatcher that picks approval vs. cancel based on
        # the currently visible bar. Textual's binding table is
        # keyed by key — having two bindings on the same letter
        # (``e`` is used by both the approval-escalate AND the
        # cancel-error options) leads to last-write-wins, which would
        # break the approval-bar path entirely. The dispatcher keeps
        # both interpretations alive while preserving the
        # mutually-exclusive UX (only one bar is visible at a time).
        Binding("a", "prompt_letter('a')", show=False, priority=True),
        Binding("r", "prompt_letter('r')", show=False, priority=True),
        Binding("e", "prompt_letter('e')", show=False, priority=True),
        Binding("t", "prompt_letter('t')", show=False, priority=True),
        Binding("m", "prompt_letter('m')", show=False, priority=True),
        Binding("s", "prompt_letter('s')", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    /* margin-top: 1 so the composer doesn't sit flush against the
     * widget above (the plan strip when present, the transcript
     * otherwise) — gives the input visual breathing room. Border
     * tints ``$accent`` down so the chrome reads as part of the
     * same family as the ``inspect acp`` caption without competing
     * with transcript content for attention. */
    #composer-row {
        height: auto;
        min-height: 3;
        margin: 1 2 1 2;
        border: tall $accent 55%;
    }
    /* Readonly "> " so the operator reads the row as a prompt
     * (terminal convention). Dimmed accent + no bold to keep the
     * chrome quiet — the prompt is a hint, not a call to action. */
    #composer-prompt {
        width: 3;
        height: 1;
        color: $accent 55%;
        padding: 0 0 0 1;
    }
    /* Drop TextArea's own border + tint so it sits inside the wrapper
     * border as a single composer affordance instead of two stacked
     * boxes. */
    #composer {
        height: auto;
        min-height: 1;
        max-height: 8;
        width: 1fr;
        border: none;
        background: transparent;
        padding: 0;
        scrollbar-size-vertical: 1;
    }
    """

    # Tracks the previous lifecycle so ``_apply_lifecycle`` can detect
    # the approval ↔ non-approval transition and hand focus back to the
    # composer when the bar disappears. The bar itself takes focus on
    # mount; without this, focus would be stranded on the (now hidden)
    # last-pressed action button and the next keystroke would go
    # nowhere.
    _last_lifecycle: str | None = None

    def __init__(
        self,
        *,
        session: AttachedSession,
        on_disconnect: Callable[[], None],
        state: SessionState,
    ) -> None:
        super().__init__()
        self._session = session
        self._on_disconnect = on_disconnect
        self._watch_task: asyncio.Task[None] | None = None
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None
        # Set by ``action_switch_sample`` so the disconnect watcher can
        # tell a user-initiated pop from a peer-side EOF and skip the
        # otherwise-misleading "disconnected from server" toast.
        self._user_initiated_close = False

    @property
    def state(self) -> SessionState:
        return self._state

    def compose(self) -> ComposeResult:
        with Vertical():
            yield SessionHeaderWidget(self._session.row)
            yield TranscriptWidget()
            # Plan strip sits between transcript and composer so the
            # operator sees "what is the agent working on next" in the
            # immediate visual neighbourhood of the input. Self-hides
            # when the session has no plan — non-planning agents see
            # no chrome here.
            yield PlanStripWidget(self._state)
            with Horizontal(id="composer-row"):
                yield Static("> ", id="composer-prompt", markup=False)
                yield ComposerTextArea(
                    # Resting-state placeholder. ``_apply_state``
                    # appends "· esc to interrupt" while the
                    # lifecycle is ``running``.
                    placeholder="type a message",
                    id="composer",
                    soft_wrap=True,
                    show_line_numbers=False,
                    highlight_cursor_line=False,
                )
                # The approval and cancel-sample prompts no longer
                # live in the composer row — Phase 6b moves them to
                # :class:`InlineRequestCard` subclasses that mount
                # below the transcript via :meth:`_apply_request_cards`,
                # alongside the elicitation card.
        yield AppFooter()

    async def on_mount(self) -> None:
        self._apply_state()
        # Subscribe AFTER the initial paint so the first state-driven
        # refresh runs through the same _apply_state path as later
        # change notifications.
        self._unsubscribe = self._state.subscribe(self._on_state_change)
        # Time-driven status refresh — see _STATUS_TICK_SECONDS comment.
        self.set_interval(_STATUS_TICK_SECONDS, self._tick)
        self._watch_task = asyncio.create_task(self._watch_disconnect())

    async def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        await self._session.close()

    # ------------------------------------------------------------------
    # State change handling
    # ------------------------------------------------------------------

    def _on_state_change(self) -> None:
        # Subscribers fire from acp.Connection's reader task — same
        # asyncio loop as Textual, so no thread hop needed.
        self._apply_state()

    def _apply_state(self) -> None:
        try:
            header = self.query_one(SessionHeaderWidget)
            transcript = self.query_one(TranscriptWidget)
        except NoMatches:
            return
        header.set_usage(self._state.usage)
        transcript.refresh_from(self._state)
        self._apply_request_cards()
        # ``_apply_lifecycle`` calls ``refresh_bindings`` itself so the
        # ``^p plan`` footer hint flips on the same tick the strip
        # becomes visible (and so the bare-letter gates re-evaluate
        # when the cards mount / unmount).
        self._apply_lifecycle()

    def _apply_request_cards(self) -> None:
        """Mount / unmount the three inline request cards based on state.

        Single source of truth is :class:`SessionState`. Three slots
        drive three cards:

        - :attr:`SessionState.pending_elicitation` → :class:`_ElicitationCard`
        - :meth:`SessionState.current_pending_approval` → :class:`_ApprovalCard`
        - :attr:`SessionState.pending_cancel` → :class:`_CancelCard`

        Each is reconciled independently — multiple can be mounted at
        once in principle (a cancel card on top of a parked approval),
        though in practice approval and elicitation park the agent so
        cancel is the only one that can land while another card is up.
        """
        self._reconcile_card(
            _ElicitationCard,
            self._state.pending_elicitation,
            lambda pending: _ElicitationCard.from_pending(pending),
        )
        self._reconcile_card(
            _ApprovalCard,
            self._state.current_pending_approval(),
            lambda pending: _ApprovalCard.from_pending(pending),
        )
        self._reconcile_card(
            _CancelCard,
            self._state.pending_cancel,
            lambda pending: _CancelCard.from_pending(pending, self._state),
        )

    def _reconcile_card(
        self,
        card_cls: type[InlineRequestCard],
        pending: object | None,
        factory: Callable[[Any], InlineRequestCard],
    ) -> None:
        """Mount / unmount / replace a single card class.

        Three cases:

        - ``pending is None`` → unmount any existing card of this type.
        - existing card matches the current pending by identity
          (``existing.request is pending``) → no-op (re-mounting would
          steal focus and reset form state).
        - existing card belongs to a STALE pending (a second request
          of the same kind arrived before the prior card unmounted) →
          remove the stale card so the fresh one can mount.

        Mounts go right after the plan strip so the card lives in
        the same physical slot as the composer (which is hidden
        whenever a card is up). The transcript stays elastic
        (``height: 1fr``) and absorbs the slack above; the card is
        pinned just above the footer — same focus anchor as the
        composer it temporarily replaces. Because the card is a
        sibling of the transcript (not a child), it never scrolls
        out of view, which is why we don't need a separate
        auto-follow scroll for the cancel card.
        """
        existing: InlineRequestCard | None
        try:
            existing = self.query_one(card_cls)
        except NoMatches:
            existing = None
        if pending is None:
            if existing is not None:
                existing.remove()
            return
        if existing is not None:
            if existing.request is pending:
                return
            existing.remove()
        card = factory(pending)
        plan_strip = self.query_one(PlanStripWidget)
        self.query_one("Vertical").mount(card, after=plan_strip)

    def _elicitation_card_or_none(self) -> _ElicitationCard | None:
        try:
            return self.query_one(_ElicitationCard)
        except NoMatches:
            return None

    def _approval_card_or_none(self) -> _ApprovalCard | None:
        try:
            return self.query_one(_ApprovalCard)
        except NoMatches:
            return None

    def _cancel_card_or_none(self) -> _CancelCard | None:
        try:
            return self.query_one(_CancelCard)
        except NoMatches:
            return None

    def _request_card_mounted(self) -> bool:
        """``True`` while any inline request card is mounted.

        Elicitation / approval / cancel-sample cards all take the
        composer's slot in the layout. Used as the single source of
        truth for "should the composer behave as if it isn't there?":

        - :meth:`_apply_lifecycle` hides ``#composer-row`` when this
          returns True (and the TextArea is also disabled as a backup
          on the lifecycle-driven paths).
        - :meth:`action_submit` / :meth:`action_newline` bail out so a
          stray ↵ / ⇧↵ (focus drift, mouse-elsewhere click) can't ship
          or mutate the hidden draft underneath the card.

        Before this helper existed each call site listed the three
        cards inline, and the submit/newline guards forgot
        elicitation entirely — an Enter with focus off the
        elicitation form would still ``session/prompt`` the draft
        that was visually hidden. Single helper, single contract,
        no drift.
        """
        return (
            self._elicitation_card_or_none() is not None
            or self._approval_card_or_none() is not None
            or self._cancel_card_or_none() is not None
        )

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        """Hide the ``^p plan`` footer hint when there's nothing to show.

        Returns ``False`` for ``toggle_plan`` until the session has
        received its first ``AgentPlanUpdate``; once a plan exists,
        returns ``True``. Other actions fall through to the default.

        Why ``False`` and not ``None``: in Textual 8.2.3,
        ``Screen.active_bindings`` only skips bindings whose
        ``check_action`` returns the literal ``False`` (see
        ``screen.py`` ``active_bindings`` body — ``if action_state
        is False: continue``). ``None`` falls through to
        ``enabled = bool(None) = False`` and the binding renders as
        visible-but-disabled in the footer. We want the slot gone
        entirely while there's no plan to show, so ``False``.

        The same gate disables the bare-letter approval / cancel
        shortcuts so the composer ``TextArea`` still receives plain
        typing when neither bar is visible. The dispatcher key
        (``prompt_letter``) is gated to fire ONLY when either the
        approval bar or the cancel bar wants the letter — see
        :meth:`_letter_targets_visible_bar`.
        """
        if action == "toggle_plan":
            return self._state.plan_entries is not None
        if action == "cancel_sample":
            # Nothing to cancel once the sample is terminal — the
            # footer hint also disappears so the operator sees only
            # the actions that still apply. While a cancel card is
            # already mounted, ^N stays live but takes a different
            # path (scroll-to-card + re-engage auto-follow); see
            # :meth:`action_cancel_sample`.
            if self._state.lifecycle == "complete":
                return False
            return True
        if action == "cancel_tool_call":
            # Nothing to cancel when no eligible tool is in flight —
            # hide the footer hint entirely so the operator only sees
            # actions that currently apply. The ``cancel_tool_call_id``
            # accessor already filters tools awaiting an approval
            # decision (the approval bar's reject / terminate is the
            # right exit there) and tools the operator has already
            # cancel-requested.
            return self._state.cancel_tool_call_id is not None
        if action == "prompt_letter":
            if not _parameters:
                return False
            return self._letter_targets_visible_bar(str(_parameters[0]))
        # Composer-driven actions are meaningless in an observe-only
        # session: there's no bound turn loop to accept a prompt, and the
        # composer row is hidden, so ``submit`` / ``newline`` can never
        # fire. Hide their footer hints. ``interrupt`` (Esc) maps to the
        # turn-loop ``session/cancel`` — also a no-op here — so hide it
        # too, EXCEPT while a cancel / elicitation card is mounted: ^N
        # cancel_sample IS available in observe-only and the card's Esc
        # dismissal routes through :meth:`action_interrupt`.
        if action in ("submit", "newline") and not self._session.row.interactive:
            return False
        if action == "interrupt" and not self._session.row.interactive:
            return (
                self._cancel_card_or_none() is not None
                or self._elicitation_card_or_none() is not None
            )
        return True

    def _apply_lifecycle(self) -> None:
        """Push the current lifecycle to the header pill + composer.

        Split out from ``_apply_state`` because lifecycle is partly
        TIME-driven (the ``running`` quiescence tail expires N
        seconds after the last activity, without a state mutation to
        fire ``subscribe``). The periodic ``_tick`` calls this so the
        pill flips from ``running`` to ``idle`` when the tail
        actually expires rather than at the next unrelated state
        update.
        """
        try:
            header = self.query_one(SessionHeaderWidget)
        except NoMatches:
            return
        lifecycle = self._state.lifecycle
        header.set_lifecycle(lifecycle)
        # Observe-only sessions (no bound agent turn loop) can't be
        # driven — read live from the row so a binding-meta correction
        # on the direct-attach path is reflected. We simply hide the
        # composer row below; cancel-sample / cancel-tool controls stay
        # available, so it isn't a pure read-only state.
        interactive = self._session.row.interactive
        composer = self._composer_or_none()
        if composer is not None:
            # Hide the composer row entirely when there's no way for
            # the operator to use it productively:
            #
            # - An inline request card is mounted (elicitation /
            #   approval / cancel) — the card is the single thing on
            #   screen the operator should be reacting to. A queued
            #   ``session/prompt`` goes nowhere useful until the card
            #   resolves anyway.
            # - ``lifecycle in ("complete", "scoring")`` — the ACP
            #   session is gone (``complete``) or the agent loop is
            #   over and the server rejects ``session/prompt``
            #   (``scoring``). Submit would silently bounce.
            #
            # We hide ``#composer-row`` rather than just ``#composer``
            # so the ``>`` prompt static doesn't sit there orphaned.
            #
            # The placeholder + disabled assignments below remain as a
            # backup for any future state where the composer is
            # visible-but-disabled — none of the current cases hit
            # that path (every "disabled" state now also hides), but
            # cheap insurance against a regression.
            hide_composer_row = (
                self._request_card_mounted()
                or not interactive
                or lifecycle
                in (
                    "complete",
                    "scoring",
                )
            )
            try:
                composer_row = self.query_one("#composer-row")
                composer_row.display = not hide_composer_row
            except NoMatches:
                pass
            if not interactive:
                # Observe-only — no bound turn loop to accept a prompt.
                # The row is hidden above; disabling is backup insurance
                # against any future state that re-shows it.
                composer.disabled = True
            elif lifecycle == "complete":
                composer.placeholder = "sample complete"
                composer.disabled = True
            elif lifecycle == "scoring":
                composer.placeholder = "scoring"
                composer.disabled = True
            elif lifecycle == "approval":
                composer.placeholder = "awaiting your approval"
                composer.disabled = True
            else:
                composer.placeholder = (
                    "type a message · esc to interrupt"
                    if lifecycle == "running"
                    else "type a message"
                )
                composer.disabled = False
        # Focus handoff on the approval-card unmount boundary: after a
        # decision the card unmounts and any focused button is now
        # invisible, so we route focus back to the composer so the
        # operator can type again. Skip the handoff while a cancel
        # card is up; that card's first button owns focus.
        if (
            self._last_lifecycle == "approval"
            and lifecycle != "approval"
            and composer is not None
            and self._state.pending_cancel is None
        ):
            composer.focus()
        self._last_lifecycle = lifecycle
        # Bindings depend on which cards are mounted (see
        # check_action) — nudge the bindings view so the footer + key
        # dispatch stay in sync with the row owner.
        self.refresh_bindings()

    def _tick(self) -> None:
        # In-flight tool durations + the assistant chip spinner have no
        # state mutation that fires ``subscribe``, so we nudge them
        # here on a timer. Same reason ``_apply_lifecycle`` runs here:
        # the lifecycle's ``running`` quiescence tail is time-driven.
        try:
            self.query_one(TranscriptWidget).tick_inflight_durations()
        except NoMatches:
            pass
        self._apply_lifecycle()

    # ------------------------------------------------------------------
    # Disconnect watch
    # ------------------------------------------------------------------

    async def _watch_disconnect(self) -> None:
        """Tear down the connection on terminal disconnect.

        The AttachedSession's reconnect coordinator owns the transient
        disconnect cycle — it flips ``state.disconnected`` (orthogonal
        to ``lifecycle``) and emits toasts while it retries. The
        ``session.disconnected`` event fires only on TERMINAL teardown:

        - user-initiated ``^S switch sample`` (which calls ``close()``
          itself; this watcher sees the event and returns),
        - the server's ``inspect/session_ended`` notification (the
          handler already called ``mark_complete``; this watcher just
          tears down the dead transport),
        - the reconnect coordinator got ``invalid_params`` from
          ``session/load`` (the handler in the coordinator already
          called ``mark_complete``; this watcher tears down).

        In every path ``mark_complete`` is already idempotent by the
        time we get here, but we call it again as a defensive
        backstop in case a future code path sets ``disconnected``
        without going through one of the above.
        """
        try:
            await self._session.disconnected.wait()
        except asyncio.CancelledError:
            return
        # User-initiated ^S switch fires ``disconnected`` after the
        # action handler has already kicked off the pop — no need to
        # mark complete or do anything else here (``on_unmount`` will
        # run ``close()`` as the pop tears down the screen).
        if self._user_initiated_close:
            return
        # Idempotent: the session_ended handler / reconnect coordinator
        # already called mark_complete on their respective paths.
        # Defensive backstop in case a future path lands here without
        # having gone through one of the explicit transitions.
        self._state.mark_complete()
        # Tear down the ACP Connection / Sender / Dispatcher and the
        # writer NOW rather than at unmount — the screen stays
        # mounted post-completion as a read-only postmortem, so
        # ``on_unmount`` won't run for a long time (or ever, this
        # session). ``close()`` is idempotent so a later
        # user-initiated ^S unmount path stays safe.
        await self._session.close()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def on_elicitation_decision_requested(
        self, message: ElicitationDecisionRequested
    ) -> None:
        """Resolve the pending elicitation bubbled up from the inline card.

        The card's Submit / Decline button posts this message; we land
        it here and call :meth:`SessionState.resolve_elicitation`,
        which fires the ``PendingElicitation.event`` the client-side
        JSON-RPC handler is parked on. That handler then writes the
        response back over the wire and the next state-change tick
        unmounts the card via :meth:`_apply_request_cards`.
        """
        self._state.resolve_elicitation(action=message.action, content=message.content)
        message.stop()

    def on_approval_decision_requested(
        self, message: ApprovalDecisionRequested
    ) -> None:
        """Resolve the pending approval bubbled up from the inline card.

        The button-press handler on :class:`_ApprovalCard` posts this
        message; we land it here and call
        :meth:`SessionState.resolve_approval`, which fires the
        ``PendingApproval.event`` the client-side JSON-RPC handler is
        parked on. That handler then writes the response back over
        the wire.
        """
        self._state.resolve_approval(message.tool_call_id, option_id=message.option_id)
        message.stop()

    def action_approval_decide(self, option_id: str) -> None:
        """Resolve the current pending approval via a bare-letter shortcut.

        The screen's ``a`` / ``r`` / ``e`` / ``t`` / ``m`` bindings
        all dispatch here with the corresponding option id. Gated by
        :meth:`check_action` to fire only in ``approval`` lifecycle,
        so this is a defence-in-depth no-op if it somehow lands
        otherwise.

        Silently no-ops when the chosen ``option_id`` isn't in the
        request's configured options — ``human_approver(choices=...)``
        can restrict the choice set per call. Pressing ``m`` for a
        request that doesn't offer ``modify`` should do nothing,
        not raise.
        """
        if self._state.lifecycle != "approval":
            return
        pending = self._state.current_pending_approval()
        tool_call_id = self._state.current_pending_tool_call_id()
        if pending is None or tool_call_id is None:
            return
        if not any(opt.option_id == option_id for opt in pending.request.options):
            return
        self._state.resolve_approval(tool_call_id, option_id=option_id)

    def action_switch_sample(self) -> None:
        """Disconnect from the current session and return to the picker."""
        self._user_initiated_close = True
        self._on_disconnect()

    def on_session_header_widget_back_to_picker(
        self, event: SessionHeaderWidget.BackToPicker
    ) -> None:
        """Treat a click on the ``inspect acp`` title as ^S switch sample."""
        event.stop()
        self.action_switch_sample()

    def action_cancel_sample(self) -> None:
        """Park a :class:`PendingCancel` so the inline cancel card mounts.

        The card lives in the composer's slot (below the plan strip,
        above the footer) so it is always on screen — no auto-scroll
        gymnastics needed. Repeat press while a card is already up is
        a no-op: ``consume_cancel_request`` is itself idempotent and
        the card never goes out of view, so there's nothing for the
        re-press to fix.

        Gated by :meth:`check_action` against ``lifecycle ==
        "complete"`` so a stray ^N on a finished sample is a no-op.
        """
        if self._state.lifecycle == "complete":
            return
        connection = self._session.connection
        if connection is None:
            return
        self._state.consume_cancel_request(
            PendingCancel(
                fails_on_error=self._session.row.fails_on_error,
                connection=connection,
                session_id=self._session.session_id,
            )
        )

    def action_cancel_tool_call(self) -> None:
        """Cancel every eligible in-flight tool via ``^L``.

        Under parallel tool calls multiple tools share the in-flight
        state. A single press fans out to cancel all of them rather
        than dispatching one at a time. The footer hint hides via
        :meth:`check_action` when no eligible tool is in flight, so
        a stray ``^L`` press in a resting state is also a no-op here.

        :meth:`_dispatch_cancel_tool_call` per-tool idempotence guard
        (``mark_cancel_requested``) keeps the dispatch safe if the
        list contains a stale id concurrently transitioning to
        terminal.
        """
        for tool_call_id in self._state.cancel_tool_call_ids:
            self._dispatch_cancel_tool_call(tool_call_id)

    def _dispatch_cancel_tool_call(self, tool_call_id: str) -> None:
        """Flip the card to ``cancelling…`` and fire the JSON-RPC request.

        :meth:`SessionState.mark_cancel_requested` is the load-bearing
        idempotence guard: any concurrent ^L mash hits its terminal /
        already-requested / pending-approval short-circuits and
        returns False, so we never double-fire the request. The
        natural failure-status event from the server's
        ``_call_tools.py`` timeout-synthesis path drives the visual
        transition to terminal; we don't wait for it.
        """
        connection = self._session.connection
        if connection is None:
            return
        if not self._state.mark_cancel_requested(tool_call_id):
            return
        session_id = self._session.session_id
        self.run_worker(
            self._fire_cancel_tool_call(connection, session_id, tool_call_id),
            name=f"cancel-tool-{tool_call_id}",
            exclusive=False,
        )

    async def _fire_cancel_tool_call(
        self,
        connection: Any,
        session_id: str,
        tool_call_id: str,
    ) -> None:
        """Send ``inspect/cancel_tool_call``; clear ``cancel_requested`` on failure.

        Two failure modes both require clearing the local
        ``cancel_requested`` flag so the footer returns to its normal
        in-flight rendering and ``^L`` becomes retargetable for the
        tool (otherwise the accessor's cancel-requested filter
        permanently hides it):

        - Exception (transport / RPC error) → toast + clear.
        - ``{cancelled: false}`` response → silent clear. Per the
          server contract (``connection.py::cancel_tool_call``) this
          fires when the sample is gone, the tool isn't pending any
          more, OR the pending tool had no ``_cancel_fn`` bound — in
          the last case the tool keeps running, so without this
          clear the footer stays stuck on ``cancelling…`` forever
          with no retry path.

        Success (``{cancelled: true}``) keeps the flag set: the
        natural failure-status event will land shortly and drive the
        card to terminal, at which point the ``cancelling…`` marker
        drops on its own (the rendering gates on ``not is_terminal``).
        """
        try:
            response = await connection.send_request(
                INSPECT_CANCEL_TOOL_CALL_METHOD,
                {"sessionId": session_id, "toolCallId": tool_call_id},
            )
        except Exception as exc:
            self._state.clear_cancel_requested(tool_call_id)
            self.app.notify(f"cancel tool failed: {exc}", severity="error")
            return
        if isinstance(response, dict) and response.get("cancelled") is False:
            self._state.clear_cancel_requested(tool_call_id)

    def action_cancel_decide(self, action: str) -> None:
        """Resolve a visible cancel card via a bare-letter shortcut.

        Dispatched from :meth:`action_prompt_letter` when a cancel
        card is mounted and the operator hits ``s`` or ``e``. The
        card's :meth:`_CancelCard.choose` method drives the actual
        RPC + state cleanup; the screen just routes the key through.
        """
        card = self._cancel_card_or_none()
        if card is None:
            return
        if action not in ("score", "error", "back"):
            return
        card.choose(action)  # type: ignore[arg-type]

    def action_prompt_letter(self, letter: str) -> None:
        """Dispatcher for the shared bare-letter shortcuts.

        Both the approval card and the cancel card carve letters out
        of the composer's typing surface (``a`` / ``r`` / ``e`` /
        ``t`` / ``m`` for approval, ``s`` / ``e`` for cancel).
        Textual's binding table is keyed by letter, so we register
        each letter once and dispatch here based on which card is
        mounted.

        Mutual exclusivity: the cancel card takes precedence when
        mounted, so ``e`` while a cancel card is up means "cancel:
        error", not "approval: escalate".
        """
        if self._cancel_card_or_none() is not None:
            cancel_letter_map = {"s": "score", "e": "error"}
            target = cancel_letter_map.get(letter)
            if target is not None:
                self.action_cancel_decide(target)
            return
        if self._state.current_pending_approval() is not None:
            approval_letter_map = {
                "a": "approve",
                "r": "reject",
                "e": "escalate",
                "t": "terminate",
                "m": "modify",
            }
            target = approval_letter_map.get(letter)
            if target is not None:
                self.action_approval_decide(target)

    def action_toggle_plan(self) -> None:
        """Open the plan overlay; no-op when the agent hasn't planned yet.

        Also no-op when the overlay is already on the screen stack —
        the ``PlanOverlayScreen``'s own ``^p`` binding handles the
        close case with ``priority=True``, so this handler only fires
        when no overlay is up. Both invocation paths (the ``^p``
        binding and ``PlanStripWidget.on_click``) route here.

        Passes the live :class:`SessionState` so the overlay can
        subscribe and update in place as plan changes arrive while
        it's open.
        """
        if self._state.plan_entries is None:
            return
        self.app.push_screen(PlanOverlayScreen(self._state))

    async def on_composer_text_area_submitted(
        self, event: ComposerTextArea.Submitted
    ) -> None:
        """Submit the composer draft posted by ``ComposerTextArea``."""
        event.stop()
        await self.action_submit()

    async def action_submit(self) -> None:
        """Send the composer's text to the agent as a ``session/prompt``.

        Empty composer is a no-op so a stray ``↵`` doesn't fire a
        meaningless request. Errors from the server (connection dead,
        session vanished) surface as a toast — the user still owns the
        text, since we only clear after the request returns.

        Also a no-op once the session is complete — the composer is
        already disabled in that state, but the screen binding can
        still land if focus has moved elsewhere. Belt + braces.

        Card-button focus delegation: Enter should activate a focused
        approval or cancel button, not submit the (potentially
        disabled) composer draft. The buttons normally handle Enter
        themselves, but this fallback keeps the screen binding
        harmless if it lands after focus drift.

        Scoped to widgets whose id starts with one of the card id
        prefixes (``"approve-opt-"`` or ``"cancel-sample-opt-"``) so
        unrelated focusable widgets added later don't get
        programmatic-pressed by Enter from the composer context.
        Textual's :class:`Button` exposes ``action_press`` for this
        synthetic activation.
        """
        focused = self.focused
        if (
            focused is not None
            and focused.id
            and (
                focused.id.startswith(_BUTTON_ID_PREFIX)
                or focused.id.startswith(_CANCEL_BUTTON_ID_PREFIX)
            )
            and hasattr(focused, "action_press")
        ):
            focused.action_press()
            return
        if self._state.lifecycle == "complete":
            return
        # ``scoring`` is the same shape as ``complete`` from the
        # composer's perspective: the server's prompt handler now
        # rejects messages once the agent has parked for scoring
        # (see ``LiveAcpTransport.agent_completed`` + ``connection.py``).
        # Belt-and-braces guard against the Enter binding firing
        # during a focus-change window even though ``_apply_lifecycle``
        # has disabled the TextArea.
        if self._state.lifecycle == "scoring":
            return
        # Any inline request card (elicitation / approval / cancel)
        # takes the composer's slot: ↵ that isn't delegated to a
        # focused button or form field (focus drift, transcript
        # click, a stray priority binding landing here) is a no-op
        # so the operator's draft can't ship while the card is up.
        # Pairs with :meth:`_apply_lifecycle`'s ``hide_composer_row``
        # — same predicate, single source of truth via
        # :meth:`_request_card_mounted`.
        if self._request_card_mounted():
            return
        # Approval mode: composer is disabled in ``_apply_lifecycle``,
        # but its ``text`` is intact so a stray ↵ landing here via
        # focus drift could still ship a queued draft. Belt-and-
        # braces guard. (The approval card is included in
        # ``_request_card_mounted`` above but the lifecycle check
        # also catches the brief window between
        # ``mark_approval_started`` and the card mounting.)
        if self._state.lifecycle == "approval":
            return
        composer = self._composer_or_none()
        if composer is None:
            return
        text = composer.text.strip()
        if not text:
            return
        # Transport-level guard: the reconnect coordinator may be
        # actively retrying. Sending into a dead writer would either
        # raise (caller-visible toast we'd then show) or, worse,
        # block on ``send_request``'s response future that the dead
        # receive loop will never resolve. Bail with an honest
        # message and leave the draft intact so the operator can
        # re-send the moment the dot flips back to green.
        if self._state.disconnected:
            self.app.notify(
                "Not connected to ACP server — message not sent",
                severity="warning",
            )
            return
        connection = self._session.connection
        if connection is None:
            self.app.notify("not connected", severity="warning")
            return
        # Optimistic in-transcript echo for sends that will hit the
        # server's ``submit_user_message`` queue rather than draining
        # immediately. Without this the operator sees nothing between
        # Enter and the next ``before_turn`` (potentially many seconds
        # for a long tool run) and worries the message was lost. The
        # ephemeral renders dim with a ``user · queued`` chip and is
        # popped when the server echoes the real chunk back. Subsequent
        # sends-while-busy APPEND to the existing ephemeral (single
        # bucket) so the row matches the server-side coalesced merge
        # — the user sees exactly what the model will see. Skip while
        # ``idle``: the agent is parked in ``before_turn`` and the
        # chunk arrives within ms, so an ephemeral would just flash.
        # See :attr:`state.MessageGroup.is_queued` for the lifecycle.
        handle: _QueuedEnqueueHandle | None = None
        if self._state.lifecycle != "idle":
            handle = self._state.enqueue_queued_user_message(text)
        try:
            await connection.send_request(
                "session/prompt",
                {
                    "sessionId": self._session.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
        except Exception as exc:
            # Roll back the optimistic echo — the server never accepted
            # the message, so leaving the appended text mounted would
            # lie about its state. Restores the prior text on the
            # append path or removes the whole group on fresh creation.
            if handle is not None:
                self._state.undo_queued_enqueue(handle)
            self.app.notify(f"failed to send: {exc}", severity="error")
            return
        composer.clear()

    def action_newline(self) -> None:
        r"""Insert a literal newline at the composer cursor.

        Inserts a visible line break into the composer. TextArea's
        default Enter behavior is newline, but the composer intercepts
        Enter for submit, so newlines go through this explicit
        Shift+Enter / Ctrl+J action.

        No-op once the session is complete — same belt-and-braces
        reasoning as ``action_submit``: the composer is disabled in
        that state, but ``shift+enter`` is ``priority=True`` so the
        binding could still fire during a focus-change window.
        Without this guard a "read-only" completed transcript could
        still accumulate locally-inserted newlines.

        Also a no-op while any inline request card is mounted
        (elicitation / approval / cancel-sample): the composer row
        is hidden by :meth:`_apply_lifecycle` but its ``text`` is
        intact, so a stray ⇧↵ would otherwise smuggle a literal
        ``\\n`` into the invisible draft, which then ships to the
        agent on the next submit. Single predicate via
        :meth:`_request_card_mounted` — mirrors the matching guard
        in :meth:`action_submit`.
        """
        if self._state.lifecycle in ("complete", "scoring", "approval"):
            return
        if self._request_card_mounted():
            return
        composer = self._composer_or_none()
        if composer is None:
            return
        composer.insert("\n")

    async def action_interrupt(self) -> None:
        """Dismiss the cancel card, dismiss the elicitation card, clear the composer draft, or interrupt the turn.

        Layered escape semantics (in precedence order):

        1. Cancel card mounted → resolve it as Back (the operator
           backed out of cancelling). No interrupt, no composer change.
        2. Elicitation card mounted → decline it (the operator is
           saying "no thanks, I won't answer"). Mirrors clicking
           the card's Decline button.
        3. Composer has a draft → clear it (so a typo is easy to undo).
        4. Agent is working → send ``session/cancel``.

        The card takeovers are the highest-priority cases because
        ``esc`` reads as "back out of this prompt" in every card /
        bar pattern the TUI uses; firing an unrelated session-cancel
        from the same key would be jarring.

        Cancel beats elicitation when both cards coexist: ^N is
        still allowed while an elicitation is pending, so the
        operator can have both cards mounted simultaneously. In
        that case the cancel card is the *more recent* operator
        decision (typed ^N after the question had already
        mounted), so Esc reads as "back out of this prompt I
        just opened", not "decline the earlier question that's
        still sitting there". A second Esc then declines the
        elicitation if the operator wants — two presses handle
        both cards in order.

        Step 4 is gated on :attr:`SessionState.has_active_work`
        (pending model events OR in-flight tools) rather than the
        looser display :attr:`StatusState.GENERATING`, which also
        fires for the 2-second quiescence tail after a normal
        response. Cancelling during that tail would manufacture a
        misleading ``between_turns`` ``InterruptEvent`` on the
        server.
        """
        cancel_card = self._cancel_card_or_none()
        if cancel_card is not None:
            if cancel_card._resolved:
                # Score/Error has already fired the
                # ``inspect/cancel_sample`` RPC and the card is
                # in its "Cancelling…" presentation. Esc is a
                # no-op until the RPC settles — clearing
                # ``pending_cancel`` here would unmount the card
                # underneath the in-flight worker and the UI would
                # lie about "keep running" while the sample
                # actually proceeds to cancel.
                return
            self._state.resolve_cancel()
            composer = self._composer_or_none()
            if composer is not None:
                composer.focus()
            return
        elicit_card = self._elicitation_card_or_none()
        if elicit_card is not None:
            # Route through the same message the Decline button
            # posts so resolve_elicitation + unmount + composer
            # re-focus all run on the single screen-level handler.
            elicit_card.post_message(ElicitationDecisionRequested(action="decline"))
            return
        composer = self._composer_or_none()
        if composer is not None and composer.text:
            composer.clear()
            return
        if not self._state.has_active_work:
            return
        connection = self._session.connection
        if connection is None:
            return
        # Clear local in-flight signals BEFORE sending so the spinner /
        # status pill react instantly rather than waiting for the
        # server's cancel propagation to round-trip back to us.
        self._state.mark_interrupted()
        try:
            await connection.send_notification(
                "session/cancel",
                {"sessionId": self._session.session_id},
            )
        except Exception as exc:
            self.app.notify(f"failed to interrupt: {exc}", severity="error")

    # ------------------------------------------------------------------
    # Composer-row helpers
    # ------------------------------------------------------------------

    def _composer_or_none(self) -> ComposerTextArea | None:
        """The composer TextArea, or None if it isn't mounted (defensive)."""
        try:
            return self.query_one("#composer", ComposerTextArea)
        except NoMatches:
            return None

    def _letter_targets_visible_bar(self, letter: str) -> bool:
        """Whether ``letter`` should activate a visible inline card.

        Returns True iff the letter maps to an option on a card that
        is currently mounted. Used by :meth:`check_action` to gate
        the bare-letter bindings so the composer ``TextArea`` still
        receives plain typing when no card is up.

        Cancel card takes precedence: ``e`` while a cancel card is
        mounted activates ``Cancel: Error`` (when offered), not the
        approval ``escalate``.
        """
        cancel_card = self._cancel_card_or_none()
        if cancel_card is not None:
            if letter == "s":
                return True
            if letter == "e":
                # ``e`` is only live when the cancel card actually
                # rendered the error option (depends on the
                # ``fails_on_error`` flag). Probing the DOM keeps the
                # gate honest without duplicating the policy here.
                try:
                    cancel_card.query_one(f"#{_CANCEL_BUTTON_ID_PREFIX}error")
                except NoMatches:
                    return False
                return True
            return False
        if self._state.current_pending_approval() is not None:
            return letter in ("a", "r", "e", "t", "m")
        return False
