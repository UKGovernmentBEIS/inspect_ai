"""Session screen for the ``inspect acp`` TUI.

Layout:

  - :class:`SessionHeaderWidget` — single-row app title + meta
    identifiers (task / sample / epoch / agent / tokens) + connection
    indicator.
  - :class:`TranscriptWidget` — scrollable conversation pane.
  - Composer ``Input`` — user types prompts; ``↵`` sends, ``Esc``
    interrupts (or clears the draft when one is present).
  - Textual ``Footer`` for keymap hints.

A periodic ``set_interval`` timer calls ``_tick`` so in-flight tool
duration counters and the assistant chip spinner keep ticking even
between notifications.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Input, Static

from .client import AttachedSession
from .state import SessionState
from .widgets import (
    AppFooter,
    PlanStripWidget,
    SessionHeaderWidget,
    TranscriptWidget,
)
from .widgets.approval_bar import _ApprovalBar
from .widgets.plan import PlanOverlayScreen
from .widgets.tool_call import _BUTTON_ID_PREFIX, ApprovalDecisionRequested

_STATUS_TICK_SECONDS = 0.5
"""How often time-driven UI bits get nudged.

In-flight tool durations + the assistant chip spinner don't have
state mutations that fire ``subscribe``, so the screen ticks them on
this interval. Sub-second so the motion feels responsive; not so
fast that idle CPU is wasted.
"""


class SessionScreen(Screen[None]):
    """Phase 2 attached-session view."""

    # ``priority=True`` on every binding so they fire regardless of
    # focused widget — the composer ``Input`` would otherwise eat
    # ``enter`` (firing its own ``Input.Submitted``) and the screen
    # action never runs. Same reasoning for ``escape``; same for ^S so
    # the user can always leave the session.
    BINDINGS = [
        Binding("enter", "submit", "submit", show=True, key_display="↵", priority=True),
        # ``shift+enter`` inserts a literal ``\n`` into the composer
        # value. The current single-line ``Input`` doesn't render the
        # newline locally — it survives in ``Input.value`` and ships
        # to the server on submit, but the composer column shows the
        # text as one line until we swap the composer for ``TextArea``.
        # Advertising the shortcut now so muscle memory matches the
        # eventual visible behaviour.
        Binding(
            "shift+enter",
            "newline",
            "newline",
            show=True,
            key_display="⇧↵",
            priority=True,
        ),
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
        Binding(
            "ctrl+s",
            "switch_sample",
            "switch sample",
            show=True,
            priority=True,
        ),
        # Approval bar shortcuts — bare letters matching the
        # underlined character on each ``_ApprovalBar`` button. Gated
        # by :meth:`check_action` to fire ONLY while the lifecycle is
        # ``approval`` so the composer ``Input`` still receives
        # regular typing the rest of the time. ``show=False`` because
        # the bar itself renders the keys (``[ a ] approve``, etc.) —
        # duplicating them in the footer would just add noise.
        Binding(
            "a", "approval_decide('approve')", "approve", show=False, priority=True
        ),
        Binding("r", "approval_decide('reject')", "reject", show=False, priority=True),
        Binding(
            "e", "approval_decide('escalate')", "escalate", show=False, priority=True
        ),
        Binding(
            "t", "approval_decide('terminate')", "terminate", show=False, priority=True
        ),
        Binding("m", "approval_decide('modify')", "modify", show=False, priority=True),
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
        height: 3;
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
    /* Drop Input's own border + tint so it sits inside the wrapper
     * border as a single composer affordance instead of two stacked
     * boxes. */
    #composer {
        height: 1;
        width: 1fr;
        border: none;
        background: transparent;
        padding: 0;
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
                yield Input(
                    # Resting-state placeholder. ``_apply_state``
                    # appends "· esc to interrupt" while the
                    # lifecycle is ``running``.
                    placeholder="type a message",
                    id="composer",
                )
                # Composer-mode approval bar — hides itself when no
                # approval is pending. When visible, ``_apply_lifecycle``
                # also hides the ``#composer`` ``Input`` so the bar
                # takes the row.
                yield _ApprovalBar(self._state)
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
        self._apply_lifecycle()
        # Plan strip self-hides via subscriber callback; the ``^p``
        # footer hint is gated by :meth:`check_action`, which Textual
        # only consults on demand. Nudge the bindings view so the
        # footer flips on the same tick the strip becomes visible.
        self.refresh_bindings()

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

        The same gate disables the bare-letter approval shortcuts
        (``a`` / ``r`` / ``e`` / ``t`` / ``m``) outside ``approval``
        lifecycle. Without this gate, typing ``r`` into the composer
        would fire the reject action instead of inserting the letter.
        """
        if action == "toggle_plan":
            return self._state.plan_entries is not None
        if action == "approval_decide":
            return self._state.lifecycle == "approval"
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
        if composer is not None:
            # Approval mode replaces the composer ``Input`` with the
            # ``_ApprovalBar`` (same row, sibling widget). The bar
            # self-shows from its state subscription; we just need to
            # hide the Input so the bar gets the row.
            if lifecycle == "approval":
                composer.display = False
            else:
                composer.display = True
            # Three placeholder states for the visible-Input cases.
            # The composer goes read-only on ``complete``: the ACP
            # session is gone so a submit would silently round-trip
            # into the void. Better to surface that the session is
            # finished and freeze the input than to let the operator
            # type into a dead pipe.
            if lifecycle == "complete":
                composer.placeholder = "sample complete"
                composer.disabled = True
            elif lifecycle == "approval":
                # Placeholder isn't visible (Input is hidden) but kept
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
        # Focus handoff on the approval ↔ non-approval boundary. The
        # bar's ``_mount_buttons`` focuses its first button when an
        # approval appears, so the enter-approval direction is
        # already covered. The exit direction is the one that needs
        # explicit handling — after a decision the bar hides and any
        # focused button is now invisible, so we route focus back to
        # the composer so the operator can type again.
        if (
            self._last_lifecycle == "approval"
            and lifecycle != "approval"
            and composer is not None
        ):
            composer.focus()
        self._last_lifecycle = lifecycle

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
        """Flip the lifecycle pill to ``complete`` when the peer goes away.

        The client's receive-task sets ``disconnected`` on EOF / read
        error / explicit close. ACP has no explicit "session
        complete" notification today, so transport disconnect is the
        signal we have: the inspect agent loop returned, the server
        tore the session down, no more updates are coming.

        The previous behaviour popped back to the picker, which made
        the transcript unreadable post-completion. Now we leave the
        UI in place (so the operator can review the final state)
        and just mark the session complete in state — the header
        pill picks that up via the next ``_apply_state`` notify.

        ^S still pops manually via ``action_switch_sample``.
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

    async def action_submit(self) -> None:
        """Send the composer's text to the agent as a ``session/prompt``.

        Empty composer is a no-op so a stray ``↵`` doesn't fire a
        meaningless request. Errors from the server (connection dead,
        session vanished) surface as a toast — the user still owns the
        text, since we only clear after the request returns.

        Also a no-op once the session is complete — the composer is
        already disabled in that state, but the binding is
        ``priority=True`` so a stray ↵ during a focus-change window
        could still land. Belt + braces.

        Approval-action focus delegation: the ``enter`` binding is
        ``priority=True`` (so the composer ``Input`` doesn't eat it
        and fire ``Input.Submitted`` instead). That ALSO eats Enter
        when an approval-bar action has focus — its own ``enter``
        binding never gets a chance to fire. Detect the case and
        programmatically press the focused widget, mirroring what
        Enter would do on an unbound screen. Without this, Tab+Enter
        through the approval bar would silently submit the
        composer's draft (or no-op when the composer is empty)
        instead of approving.

        Scoped to widgets whose id starts with ``_BUTTON_ID_PREFIX``
        (``"approve-opt-"``) so unrelated focusable widgets added
        later don't get programmatic-pressed by Enter from the
        composer context. The delegation covers both
        :class:`_ApprovalAction` (current ``Static``-based bar
        actions) and any legacy ``Button`` that adopts the same id
        convention — both expose ``action_press()``.
        """
        focused = self.focused
        if (
            focused is not None
            and focused.id
            and focused.id.startswith(_BUTTON_ID_PREFIX)
            and hasattr(focused, "action_press")
        ):
            focused.action_press()
            return
        if self._state.lifecycle == "complete":
            return
        # Approval mode: hidden composer must not be submittable.
        # The Input is ``display: none`` but its ``value`` survives —
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
        text = composer.value.strip()
        if not text:
            return
        connection = self._session.connection
        if connection is None:
            self.app.notify("not connected", severity="warning")
            return
        try:
            await connection.send_request(
                "session/prompt",
                {
                    "sessionId": self._session.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
        except Exception as exc:
            self.app.notify(f"failed to send: {exc}", severity="error")
            return
        composer.value = ""

    def action_newline(self) -> None:
        r"""Insert a literal newline at the composer cursor.

        Hint-only for now: the single-line :class:`Input` doesn't
        render the newline locally, but the character lives in
        ``Input.value`` and ships to the server on submit. When the
        composer migrates to ``TextArea`` the binding's UX will
        match the footer hint without a key-rebind.

        No-op once the session is complete — same belt-and-braces
        reasoning as ``action_submit``: the composer is disabled in
        that state, but ``shift+enter`` is ``priority=True`` so the
        binding could still fire during a focus-change window.
        Without this guard a "read-only" completed transcript could
        still accumulate locally-inserted newlines.

        Also a no-op during ``approval`` lifecycle: the Input is
        hidden but its ``value`` is intact, so a stray ⇧↵ would
        otherwise smuggle a literal ``\\n`` into the invisible
        draft, which then ships to the agent on the next submit.
        Pairs with the matching guard in :meth:`action_submit`.
        """
        if self._state.lifecycle in ("complete", "approval"):
            return
        composer = self._composer_or_none()
        if composer is None:
            return
        composer.insert_text_at_cursor("\n")

    async def action_interrupt(self) -> None:
        """Clear the composer draft, or interrupt the running turn.

        Mirrors the design-doc keymap: ``Esc`` clears the draft when
        one is present (so a typo is easy to undo). With an empty
        composer, sends ``session/cancel`` ONLY while the agent is
        actually working — gated on
        :attr:`SessionState.has_active_work` (pending model events OR
        in-flight tools) rather than the looser display
        :attr:`StatusState.GENERATING`, which also fires for the
        2-second quiescence tail after a normal response. Cancelling
        during that tail would manufacture a misleading
        ``between_turns`` ``InterruptEvent`` on the server.
        """
        composer = self._composer_or_none()
        if composer is not None and composer.value:
            composer.value = ""
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

    def _composer_or_none(self) -> Input | None:
        """The composer Input, or None if it isn't mounted (defensive)."""
        try:
            return self.query_one("#composer", Input)
        except NoMatches:
            return None
