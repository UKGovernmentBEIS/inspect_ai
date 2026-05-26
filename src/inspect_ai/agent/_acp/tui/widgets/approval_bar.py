"""Composer-area approval bar.

When a tool call needs human approval, this bar takes over the
composer row (the ``Input`` is hidden) and presents the operator
with a terminal-prompt-styled question + per-option actions:

    > approve?   [ a ] approve   [ r ] reject   [ e ] escalate   [ t ] terminate

The bracketed underlined letter on each action doubles as the
single-key shortcut (handled by ``SessionScreen``'s bindings — the
bar's option widgets are clickable and Tab-navigable, the screen's
``a`` / ``r`` / ``e`` / ``t`` bindings dispatch to the same resolver
when the lifecycle is ``approval``).

Layout choice rationale: keeping the action affordances in the
composer area anchors the operator's attention at the bottom of the
screen (where the next-thing-to-do already lives) and avoids the
"scroll up to find the buttons" issue the earlier in-card design
had on busy tool cards with diffs / code blocks. The tool card
itself still renders the context preview (view halves) so the
operator can see WHAT they're approving.

The option widgets themselves are :class:`_PromptOption` instances
from :mod:`._prompt` — same focusable / clickable / Enter-activatable
``Static`` pattern, shared with :class:`_CancelSampleBar`. The bar
provides the colour vocabulary (success / warning / error) via CSS
class selectors on the option's ``kind-…`` class.
"""

from __future__ import annotations

from typing import Callable

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from ..state import PendingApproval, SessionState
from ._prompt import _PromptOption
from .tool_call import _BUTTON_ID_PREFIX, ApprovalDecisionRequested


class _ApprovalBar(Widget):
    """Composer-area bar for resolving a pending tool-call approval.

    Hidden when no approval is pending. When one IS pending, shows
    the question + one :class:`_PromptOption` per configured
    option. Options carry the existing ``approve-opt-<option_id>``
    id convention so the screen's delegation in ``action_submit``
    (and any future id-based routing) still finds them.

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
    /* Per-kind option colours — the option widget itself stays
     * colour-neutral and the bar layers the vocabulary on top via
     * the ``kind-…`` class the option attaches. */
    _ApprovalBar _PromptOption.kind-allow-once,
    _ApprovalBar _PromptOption.kind-allow-always { color: $success; }
    _ApprovalBar _PromptOption.kind-reject-once { color: $warning; }
    _ApprovalBar _PromptOption.kind-reject-always { color: $error; }
    """

    def __init__(self, state: SessionState) -> None:
        super().__init__()
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None
        # Track which request id we last mounted options for so the
        # subscription callback can short-circuit on no-op refreshes
        # (state notifies fire on every mutation; we only need to
        # rebuild options when the actual pending request changes).
        # Also used by ``on_prompt_option_pressed`` as the
        # race-protected "what tool call did the operator just
        # decide on" — the bar's mounted request id is the truth, and
        # we compare against the live ``current_pending_tool_call_id``
        # at handler time to drop stale presses that arrive after a
        # parallel approval rotated.
        self._mounted_request_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("approve?", id="approval-question", markup=False)
        # Options mount dynamically via ``_refresh_from_state``; the
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
        - New pending (different request) → unmount old options,
          mount new ones, focus the first.
        """
        pending = self._state.current_pending_approval()
        if pending is None:
            self.add_class("-hidden")
            self._mounted_request_id = None
            self._clear_options()
            return
        request_id = pending.request.tool_call.tool_call_id
        if request_id == self._mounted_request_id:
            self.remove_class("-hidden")
            return
        self._mounted_request_id = request_id
        self._clear_options()
        self._mount_options(pending)
        self.remove_class("-hidden")

    def _clear_options(self) -> None:
        for child in list(self.query(_PromptOption)):
            child.remove()

    def _mount_options(self, pending: PendingApproval) -> None:
        for option in pending.request.options:
            # First letter of option_id doubles as the keyboard
            # shortcut. The standard Inspect ``ApprovalDecision``
            # set (approve / reject / escalate / terminate / modify)
            # has unique first letters; custom approvers that
            # collide would need explicit shortcut assignment —
            # not a v1 concern.
            key = option.option_id[0]
            self.mount(
                _PromptOption(
                    action_id=option.option_id,
                    key=key,
                    label=option.option_id,
                    kind=option.kind,
                    widget_id=f"{_BUTTON_ID_PREFIX}{option.option_id}",
                )
            )
        # Focus the first option so Tab+Enter has a sensible default
        # (mirrors the in-proc panel's ``activate`` pattern).
        first = self.query(_PromptOption).first()
        if first is not None:
            first.focus()

    def on_prompt_option_pressed(self, event: _PromptOption.Pressed) -> None:
        # Validate the press still applies to a pending request.
        # Two ways this can be stale:
        # 1. The approval already resolved (button mash, queued
        #    re-press after a fast key+click).
        # 2. The approval resolved AND a new one became current
        #    (parallel tool calls) — the live
        #    ``current_pending_tool_call_id`` differs from the bar's
        #    ``_mounted_request_id`` (which is what the options were
        #    bound to render for).
        # In both cases the right answer is to drop the press
        # silently — the bar will re-render on the next state tick
        # with the correct options for the current pending request.
        mounted = self._mounted_request_id
        if mounted is None:
            return
        current = self._state.current_pending_tool_call_id()
        if current is None or current != mounted:
            return
        self.post_message(
            ApprovalDecisionRequested(
                tool_call_id=mounted,
                option_id=event.action_id,
            )
        )
        event.stop()
