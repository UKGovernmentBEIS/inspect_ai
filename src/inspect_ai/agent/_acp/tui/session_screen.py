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
from .state import SessionState, _QueuedEnqueueHandle
from .widgets import (
    AppFooter,
    PlanStripWidget,
    SessionHeaderWidget,
    TranscriptWidget,
)
from .widgets.approval_bar import _ApprovalBar
from .widgets.cancel_sample import _BUTTON_ID_PREFIX as _CANCEL_BUTTON_ID_PREFIX
from .widgets.cancel_sample import _CancelSampleBar
from .widgets.elicitation_card import (
    ElicitationDecisionRequested,
    _ElicitationCard,
)
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
                # Composer-mode approval bar — hides itself when no
                # approval is pending. When visible, ``_apply_lifecycle``
                # also hides the ``#composer`` ``TextArea`` so the bar
                # takes the row.
                yield _ApprovalBar(self._state)
                # Composer-mode cancel-sample bar — hidden by default.
                # ``action_cancel_sample`` calls ``.show()`` on ``^N``;
                # ``_apply_lifecycle`` hides both the composer TextArea
                # and the approval bar while the cancel bar is up so
                # the row has a single owner.
                yield _CancelSampleBar()
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
        self._apply_elicitation_card(transcript)
        # ``_apply_lifecycle`` calls ``refresh_bindings`` itself so the
        # ``^p plan`` footer hint flips on the same tick the strip
        # becomes visible (and so the bare-letter gates re-evaluate
        # when the cancel bar shows / hides).
        self._apply_lifecycle()

    def _apply_elicitation_card(self, transcript: TranscriptWidget) -> None:
        """Mount / unmount the inline elicitation card based on state.

        Single source of truth is :attr:`SessionState.pending_elicitation`.
        When set we mount an :class:`_ElicitationCard` right after the
        transcript so it reads as inline conversational chrome (above
        the plan strip + composer). When cleared we remove the card —
        the answer (or decline / cancel) has been routed back over the
        wire and the tool result will land in the transcript through
        the normal ``ToolCallProgress`` flow.

        Mounts at most one card; idempotent re-application
        (subscriber fires per-state-change) is a no-op while the
        already-mounted card matches the current pending.
        """
        existing = self._elicitation_card_or_none()
        pending = self._state.pending_elicitation
        if pending is None:
            if existing is not None:
                existing.remove()
            return
        # If a card is already mounted for THE SAME pending object,
        # leave it alone — re-mounting would steal focus and reset form
        # state. If the card belongs to a stale pending (a second
        # ``ask_user`` arrived before the prior card unmounted —
        # ``consume_elicitation_request`` cancels the prior pending and
        # installs the new one in a single notify), remove the stale
        # card so we can mount the fresh one. Identity comparison
        # (``is`` not ``==``) — pending objects can structurally match
        # by coincidence but the JSON-RPC handler only resolves the
        # specific instance currently parked in state.
        if existing is not None:
            if existing.pending is pending:
                return
            existing.remove()
        card = _ElicitationCard.from_pending(pending)
        # Mount right after the transcript so the card flows visually
        # below the most recent transcript item and above the plan
        # strip / composer. ``after=`` makes Textual insert into the
        # parent container at the correct ordinal position.
        self.query_one("Vertical").mount(card, after=transcript)

    def _elicitation_card_or_none(self) -> _ElicitationCard | None:
        try:
            return self.query_one(_ElicitationCard)
        except NoMatches:
            return None

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
            # the actions that still apply. Also suppressed while the
            # cancel bar is already up so a stray ^N doesn't try to
            # re-show it (the bar's own state would survive but the
            # focus would jump back to score, which is mildly
            # confusing — better to make ^N inert in that state).
            if self._state.lifecycle == "complete":
                return False
            return not self._cancel_bar_visible()
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
        composer = self._composer_or_none()
        cancel_bar_visible = self._cancel_bar_visible()
        if composer is not None:
            # The composer row has three possible owners:
            # 1. The cancel-sample bar (highest precedence — operator
            #    just hit ^N, the choice must dominate any other UI).
            # 2. The approval bar (lifecycle == "approval"; the agent
            #    is parked awaiting permission).
            # 3. The composer ``TextArea`` (everything else).
            # Cases 1 and 2 hide the composer TextArea so the chosen bar
            # gets the row.
            if cancel_bar_visible or lifecycle == "approval":
                composer.display = False
            else:
                composer.display = True
            # Three placeholder states for the visible-TextArea cases.
            # The composer goes read-only on ``complete``: the ACP
            # session is gone so a submit would silently round-trip
            # into the void. Better to surface that the session is
            # finished and freeze the input than to let the operator
            # type into a dead pipe. ``scoring`` is the same shape —
            # the agent loop is over, the server now rejects
            # ``session/prompt`` (see ``connection.py``'s
            # ``agent_completed`` guard), so a submit during scoring
            # would just bounce. Disable the input and say so.
            if lifecycle == "complete":
                composer.placeholder = "sample complete"
                composer.disabled = True
            elif lifecycle == "scoring":
                composer.placeholder = "scoring"
                composer.disabled = True
            elif lifecycle == "approval":
                # Placeholder isn't visible (TextArea is hidden) but kept
                # accurate in case Textual flashes it during a focus /
                # display transition.
                composer.placeholder = "awaiting your approval"
                composer.disabled = False
            else:
                composer.placeholder = (
                    "type a message · esc to interrupt"
                    if lifecycle == "running"
                    else "type a message"
                )
                composer.disabled = False
        # Approval bar visibility is normally driven by its own state
        # subscription, but the cancel bar takes precedence: when
        # ^N is up we hide the approval bar too so the row has a
        # single owner. The approval bar's subscription will re-show
        # it as soon as the cancel bar hides (the pending approval is
        # unchanged in state).
        approval_bar = self._approval_bar_or_none()
        if approval_bar is not None:
            if cancel_bar_visible:
                approval_bar.add_class("-hidden")
            elif self._state.current_pending_approval() is not None:
                approval_bar.remove_class("-hidden")
        # Focus handoff on the approval ↔ non-approval boundary. The
        # bar's ``_mount_options`` focuses its first option when an
        # approval appears, so the enter-approval direction is
        # already covered. The exit direction is the one that needs
        # explicit handling — after a decision the bar hides and any
        # focused option is now invisible, so we route focus back to
        # the composer so the operator can type again. Skip the
        # handoff while the cancel bar is up; that bar owns focus.
        if (
            self._last_lifecycle == "approval"
            and lifecycle != "approval"
            and composer is not None
            and not cancel_bar_visible
        ):
            composer.focus()
        self._last_lifecycle = lifecycle
        # Bindings depend on cancel-bar visibility (see check_action) —
        # nudge the bindings view so the footer + key dispatch stay in
        # sync with the row owner.
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
        unmounts the card via :meth:`_apply_elicitation_card`.
        """
        self._state.resolve_elicitation(action=message.action, content=message.content)
        message.stop()

    def on_approval_decision_requested(
        self, message: ApprovalDecisionRequested
    ) -> None:
        """Resolve the pending approval bubbled up from the composer bar.

        The button-press handler on :class:`_ApprovalBar` posts this
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
        """Show the cancel-sample composer-area bar.

        The bar takes over the composer row (the ``TextArea`` and any
        visible approval bar hide) and presents the operator with
        ``Cancel: Score`` / ``Cancel: Error`` / ``Go Back`` options.
        The bar fires ``inspect/cancel_sample`` itself when the
        operator picks a disposition; we just toggle visibility here.

        Gated by :meth:`check_action` against ``lifecycle ==
        "complete"`` so a stray ^N on a finished sample is a no-op,
        and against an already-visible bar so a repeat ^N doesn't
        re-mount and steal focus. The handler itself
        defence-in-depth re-checks before showing.
        """
        if self._state.lifecycle == "complete":
            return
        bar = self._cancel_bar_or_none()
        if bar is None or bar.is_visible:
            return
        connection = self._session.connection
        if connection is None:
            return
        bar.show(
            fails_on_error=self._session.row.fails_on_error,
            connection=connection,
            session_id=self._session.session_id,
            state=self._state,
        )
        self._apply_lifecycle()

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
        """Resolve a visible cancel bar via a bare-letter shortcut.

        Dispatched from :meth:`action_prompt_letter` when the cancel
        bar is up and the operator hits ``s`` or ``e``. The bar's
        :meth:`_CancelSampleBar.choose` method drives the actual
        RPC + hide; the screen just routes the key through.
        """
        bar = self._cancel_bar_or_none()
        if bar is None or not bar.is_visible:
            return
        if action not in ("score", "error", "back"):
            return
        bar.choose(action)  # type: ignore[arg-type]
        self._apply_lifecycle()

    def action_prompt_letter(self, letter: str) -> None:
        """Dispatcher for the shared bare-letter shortcuts.

        Both the approval bar and the cancel bar carve letters out of
        the composer's typing surface (``a`` / ``r`` / ``e`` / ``t``
        / ``m`` for approval, ``s`` / ``e`` for cancel). Textual's
        binding table is keyed by letter, so we register each letter
        once and dispatch here based on which bar is visible.

        Mutual exclusivity: the cancel bar takes precedence when
        visible (it dominates the row), so ``e`` while the cancel
        bar is up means "cancel: error", not "approval: escalate".
        """
        if self._cancel_bar_visible():
            cancel_letter_map = {"s": "score", "e": "error"}
            target = cancel_letter_map.get(letter)
            if target is not None:
                self.action_cancel_decide(target)
            return
        if self._state.lifecycle == "approval":
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

        Prompt-bar focus delegation: Enter should activate a focused
        approval or cancel option, not submit the hidden composer
        draft. The prompt options normally handle Enter themselves,
        but this fallback keeps the screen binding harmless if it
        lands after focus drift.

        Scoped to widgets whose id starts with one of the bar id
        prefixes (``"approve-opt-"`` or ``"cancel-sample-opt-"``)
        so unrelated focusable widgets added later don't get
        programmatic-pressed by Enter from the composer context.
        Both :class:`_PromptOption` instances expose
        :meth:`action_press`.
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
        # Cancel bar takes the row: ↵ that isn't delegated to a
        # focused option (focus drift, transcript click) is a no-op
        # so the operator's draft doesn't ship while the cancel
        # prompt is up.
        if self._cancel_bar_visible():
            return
        # Approval mode: hidden composer must not be submittable.
        # The TextArea is ``display: none`` but its ``text`` survives —
        # if focus is stranded on the transcript, a tool card, or any
        # non-approval widget AND the operator hits ↵, the
        # ``priority=True`` Enter binding would otherwise drop into
        # the composer-submit path below and ship the invisible draft
        # to the agent while the agent is parked awaiting permission.
        # Belt-and-braces guard: when the bar is up, ↵ that isn't
        # delegated to an approval action is a no-op.
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

        Also a no-op during ``approval`` lifecycle: the TextArea is
        hidden but its ``text`` is intact, so a stray ⇧↵ would
        otherwise smuggle a literal ``\\n`` into the invisible
        draft, which then ships to the agent on the next submit.
        Pairs with the matching guard in :meth:`action_submit`.
        """
        if self._state.lifecycle in ("complete", "scoring", "approval"):
            return
        if self._cancel_bar_visible():
            return
        composer = self._composer_or_none()
        if composer is None:
            return
        composer.insert("\n")

    async def action_interrupt(self) -> None:
        """Dismiss the cancel bar, clear the composer draft, or interrupt the turn.

        Layered escape semantics (in precedence order):

        1. Cancel bar visible → dismiss it (the operator backed out
           of cancelling). No interrupt, no composer change.
        2. Composer has a draft → clear it (so a typo is easy to undo).
        3. Agent is working → send ``session/cancel``.

        The cancel-bar takeover is the highest-priority case because
        ``esc`` reads as "back out of this prompt" in every modal /
        bar pattern the TUI uses; firing an unrelated session-cancel
        from the same key would be jarring.

        Step 3 is gated on :attr:`SessionState.has_active_work`
        (pending model events OR in-flight tools) rather than the
        looser display :attr:`StatusState.GENERATING`, which also
        fires for the 2-second quiescence tail after a normal
        response. Cancelling during that tail would manufacture a
        misleading ``between_turns`` ``InterruptEvent`` on the
        server.
        """
        bar = self._cancel_bar_or_none()
        if bar is not None and bar.is_visible:
            bar.hide()
            self._apply_lifecycle()
            composer = self._composer_or_none()
            if composer is not None:
                composer.focus()
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

    def _approval_bar_or_none(self) -> _ApprovalBar | None:
        """The composer-row approval bar, or None if it isn't mounted."""
        try:
            return self.query_one(_ApprovalBar)
        except NoMatches:
            return None

    def _cancel_bar_or_none(self) -> _CancelSampleBar | None:
        """The composer-row cancel-sample bar, or None if it isn't mounted."""
        try:
            return self.query_one(_CancelSampleBar)
        except NoMatches:
            return None

    def _cancel_bar_visible(self) -> bool:
        """Whether the cancel-sample bar is currently showing."""
        bar = self._cancel_bar_or_none()
        return bar is not None and bar.is_visible

    def _letter_targets_visible_bar(self, letter: str) -> bool:
        """Whether ``letter`` should activate a visible composer-area bar.

        Returns True iff the letter maps to an option on the bar
        that currently owns the composer row. Used by
        :meth:`check_action` to gate the bare-letter bindings so
        the composer ``TextArea`` still receives plain typing when
        neither bar is visible.

        Cancel bar takes precedence: ``e`` while the cancel bar is
        up activates ``Cancel: Error`` (when offered), not the
        approval ``escalate``.
        """
        if self._cancel_bar_visible():
            if letter == "s":
                return True
            if letter == "e":
                # ``e`` is only live when the cancel bar actually
                # rendered the error option (depends on the row's
                # ``fails_on_error`` flag). Probing the DOM keeps the
                # gate honest without duplicating the policy here.
                bar = self._cancel_bar_or_none()
                if bar is None:
                    return False
                try:
                    bar.query_one(f"#{_CANCEL_BUTTON_ID_PREFIX}error")
                except NoMatches:
                    return False
                return True
            return False
        if self._state.lifecycle == "approval":
            return letter in ("a", "r", "e", "t", "m")
        return False
