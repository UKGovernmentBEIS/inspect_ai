"""Composer-area approval bar.

When a tool call needs human approval, this bar takes over the
composer row (the ``Input`` is hidden) and presents the operator
with a terminal-prompt-styled question + per-option actions:

    > approve?   [ a ] approve   [ r ] reject   [ e ] escalate   [ t ] terminate

The bracketed underlined letter on each action doubles as the
single-key shortcut (handled by ``SessionScreen``'s bindings — the
bar's action widgets are clickable and Tab-navigable, the screen's
``a`` / ``r`` / ``e`` / ``t`` bindings dispatch to the same resolver
when the lifecycle is ``approval``).

Layout choice rationale: keeping the action affordances in the
composer area anchors the operator's attention at the bottom of the
screen (where the next-thing-to-do already lives) and avoids the
"scroll up to find the buttons" issue the earlier in-card design
had on busy tool cards with diffs / code blocks. The tool card
itself still renders the context preview (view halves) so the
operator can see WHAT they're approving.

Implementation note: actions are :class:`Static` widgets, not
:class:`Button`. Textual's ``Button`` ships with a heavy
``.-style-default`` ruleset (``background: $surface``, top/bottom
``border: tall``, ``text-style: bold``, ``content-align: center
middle``) baked into nested selectors that a per-widget DEFAULT_CSS
can't cleanly defeat. Static-based actions render as plain coloured
text — exactly what the bar's terminal-prompt aesthetic needs — and
we get keyboard / mouse / focus support via ``can_focus`` plus a
small ``Enter`` binding.
"""

from __future__ import annotations

from typing import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ..state import PendingApproval, SessionState
from .tool_call import _BUTTON_ID_PREFIX, ApprovalDecisionRequested


class _ApprovalAction(Static, can_focus=True):
    """One clickable, focusable, Enter-activatable action in the bar.

    Rendered as plain coloured text (``[ [underline]a[/] ] approve``)
    so the bar reads as a terminal prompt continuation rather than a
    row of widgetised boxes. ``can_focus = True`` puts the widget in
    Textual's Tab chain; the ``enter`` binding lets a focused action
    fire its press without help from the screen's ``action_submit``
    delegation.

    Each instance posts :class:`~_ApprovalAction.Pressed` with its
    own ``option_id`` on mouse-click OR Enter — the bar translates
    that into the screen-facing
    :class:`~widgets.tool_call.ApprovalDecisionRequested`.
    """

    DEFAULT_CSS = """
    _ApprovalAction {
        height: 1;
        width: auto;
        padding: 0 1;
        margin: 0 1 0 0;
        color: $foreground;
    }
    /* Focused action gets a subtle background highlight so the
     * operator can see which one Enter / mouse-down will hit. The
     * letter is always underlined; this adds the focus cue without
     * fighting the colour-by-kind scheme. */
    _ApprovalAction:focus {
        background: $boost;
    }
    _ApprovalAction.kind-allow-once,
    _ApprovalAction.kind-allow-always { color: $success; }
    _ApprovalAction.kind-reject-once { color: $warning; }
    _ApprovalAction.kind-reject-always { color: $error; }
    """

    BINDINGS = [
        Binding("enter", "press", show=False),
        Binding("space", "press", show=False),
    ]

    class Pressed(Message, namespace="approval_action"):
        """Emitted when the action fires (click or Enter / Space).

        Carries both ``tool_call_id`` and ``option_id`` so the
        receiver can validate the press still applies. With parallel
        approvals (or a queued press that arrived after the first
        request resolved), looking up ``current_pending_tool_call_id``
        at handler time would risk applying the press to whichever
        approval is *now* at the head of the queue — a different
        tool call than the one the operator clicked. Binding the
        target at mount time and validating on dispatch eliminates
        the race.

        ``namespace="approval_action"`` forces the receive-side handler
        name to ``on_approval_action_pressed``. Without it Textual
        derives the name from ``_ApprovalAction.Pressed.__qualname__``
        and preserves the leading underscore on the class — producing
        ``on__approval_action_pressed`` (double underscore) which is
        easy to typo-mismatch with the handler.
        """

        def __init__(self, tool_call_id: str, option_id: str) -> None:
            super().__init__()
            self.tool_call_id = tool_call_id
            self.option_id = option_id

    def __init__(self, tool_call_id: str, option_id: str, kind: str) -> None:
        key = option_id[0]
        label = Text.from_markup(f"\\[ [underline]{key}[/] ] {option_id}")
        super().__init__(label, id=f"{_BUTTON_ID_PREFIX}{option_id}")
        self._tool_call_id = tool_call_id
        self._option_id = option_id
        self.add_class(f"kind-{kind.replace('_', '-')}")

    def action_press(self) -> None:
        self.post_message(self.Pressed(self._tool_call_id, self._option_id))

    def on_click(self, event: Click) -> None:
        self.post_message(self.Pressed(self._tool_call_id, self._option_id))
        event.stop()


class _ApprovalBar(Widget):
    """Composer-area bar for resolving a pending tool-call approval.

    Hidden when no approval is pending. When one IS pending, shows
    the question + one :class:`_ApprovalAction` per configured
    option. Actions carry the existing
    ``approve-opt-<option_id>`` id convention so the screen's
    delegation in ``action_submit`` (and any future id-based
    routing) still finds them.

    Subscribes to :class:`SessionState` so it auto-shows /
    auto-hides as approvals arrive and resolve. When multiple
    approvals are pending simultaneously (parallel tool calls), the
    bar shows the first one in attach order and advances on each
    resolve.
    """

    DEFAULT_CSS = """
    _ApprovalBar {
        layout: horizontal;
        height: 1;
        width: 1fr;
    }
    _ApprovalBar.-hidden { display: none; }
    /* Question label sits left of the actions; muted grey so the
     * eye lands on the choices. */
    _ApprovalBar #approval-question {
        width: auto;
        color: $foreground 55%;
        padding-right: 2;
    }
    """

    def __init__(self, state: SessionState) -> None:
        super().__init__()
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None
        # Track which request id we last mounted actions for so the
        # subscription callback can short-circuit on no-op refreshes
        # (state notifies fire on every mutation; we only need to
        # rebuild actions when the actual pending request changes).
        self._mounted_request_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("approve?", id="approval-question", markup=False)
        # Actions mount dynamically via ``_refresh_from_state``; the
        # set + colour vocabulary depends on the configured
        # ``human_approver`` choices (which vary per call).

    def on_mount(self) -> None:
        self._unsubscribe = self._state.subscribe(self._refresh_from_state)
        # Start hidden — the subscription will flip us visible the
        # moment a pending approval arrives.
        self.add_class("-hidden")
        self._refresh_from_state()

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _refresh_from_state(self) -> None:
        """Re-render based on the current pending approval (if any).

        Three cases:
        - No pending → hide.
        - Same pending as last render → no DOM change (state notify
          spam is common; we don't want to re-mount on every chunk).
        - New pending (different request) → unmount old actions,
          mount new ones, focus the first.
        """
        pending = self._state.current_pending_approval()
        if pending is None:
            self.add_class("-hidden")
            self._mounted_request_id = None
            self._clear_actions()
            return
        request_id = pending.request.tool_call.tool_call_id
        if request_id == self._mounted_request_id:
            self.remove_class("-hidden")
            return
        self._mounted_request_id = request_id
        self._clear_actions()
        self._mount_actions(pending)
        self.remove_class("-hidden")

    def _clear_actions(self) -> None:
        for child in list(self.query(_ApprovalAction)):
            child.remove()

    def _mount_actions(self, pending: PendingApproval) -> None:
        # Bind the action to the SPECIFIC tool_call_id it's
        # presenting. The handler uses the carried id (not a fresh
        # ``current_pending_tool_call_id`` lookup) so a queued click
        # / Enter that lands after the first approval resolves
        # doesn't accidentally apply to the next pending approval.
        tool_call_id = pending.request.tool_call.tool_call_id
        for option in pending.request.options:
            # First letter of option_id doubles as the keyboard
            # shortcut. The standard Inspect ``ApprovalDecision``
            # set (approve / reject / escalate / terminate / modify)
            # has unique first letters; custom approvers that
            # collide would need explicit shortcut assignment —
            # not a v1 concern.
            self.mount(_ApprovalAction(tool_call_id, option.option_id, option.kind))
        # Focus the first action so Tab+Enter has a sensible default
        # (mirrors the in-proc panel's ``activate`` pattern).
        first = self.query(_ApprovalAction).first()
        if first is not None:
            first.focus()

    def on_approval_action_pressed(self, event: _ApprovalAction.Pressed) -> None:
        # Validate the press still applies to a pending request.
        # Two ways this can be stale:
        # 1. The approval already resolved (button mash, queued
        #    re-press after a fast key+click).
        # 2. The approval resolved AND a new one became current
        #    (parallel tool calls) — the carried ``tool_call_id``
        #    differs from whatever's pending now.
        # In both cases the right answer is to drop the press
        # silently — the bar will re-render on the next state tick
        # with the correct actions for the current pending request.
        current = self._state.current_pending_tool_call_id()
        if current is None or current != event.tool_call_id:
            return
        self.post_message(
            ApprovalDecisionRequested(
                tool_call_id=event.tool_call_id,
                option_id=event.option_id,
            )
        )
        event.stop()
