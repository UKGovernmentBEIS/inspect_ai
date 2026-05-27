"""Scrollable transcript container — mounts message + tool-call widgets.

Driven by :class:`SessionState`. Re-syncing is incremental: new items
mount, existing items update IN PLACE via their own ``update_state``
so streaming-text chunks within a message visibly extend without
churning the whole transcript. Auto-scrolls to bottom on new items
when the user was already at the bottom — preserves manual scroll-back
without losing live-tail.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.timer import Timer
from textual.widget import Widget

from ..state import EventChip, MessageGroup, ScoreChip, SessionState, ToolCallState
from ._fingerprint import tool_state_fingerprint
from .event_chip import EventChipWidget
from .message import MessageWidget
from .score import ScoreChipWidget
from .tool_call import ToolCallWidget

_SCROLL_DEBOUNCE_SECONDS = 0.08
"""How long to wait for content to settle before kicking off a scroll.

Each content change resets the timer; the animated scroll only fires
once nothing new has arrived for this long. Coalesces the
"tool-result completes → assistant message mounts" sequence into a
single glide instead of two back-to-back animations, which the user
otherwise perceives as the second leg "snapping" in. Short enough
not to feel sluggish; long enough that streaming bursts settle into
one smooth motion.
"""

_SCROLL_ANIMATE_SECONDS = 0.25
"""Duration of the animated scroll-to-end glide."""

_AT_BOTTOM_TOLERANCE = 8
"""Rows of slack when deciding "is the user at the bottom?".

Generous because the auto-follow needs to keep firing even when the
user's view is sitting just above the bottom and we still want to
be tracking. This tolerance gates whether :meth:`_schedule_scroll_to_end`
*starts* an auto-follow; exactness — "did the animation actually
reach max_scroll_y?" — lives in :meth:`_on_scroll_settled`'s strict
check, not here.
"""

_USER_SCROLL_AWAY_TOLERANCE = 3
"""Rows the user must scroll up before we conclude they pulled away.

We can't directly observe user input — instead we capture scroll_y
at scheduling and target time, and compare to the current scroll_y
at fire / settle time. A small tolerance absorbs rounding from the
animation engine without false-positive-detecting an actual user
pullaway.
"""


def _message_fingerprint(
    group: MessageGroup,
) -> tuple[int, int, str, bool, int]:
    """Detect message content changes cheaply.

    Captures all the streaming mutations Phase 2 cares about: chunks
    extending the last segment (len changes), a new segment starting
    (count changes), a later chunk supplying ``_meta["inspect.model"]``
    for the first time (model changes), the pending → completed flip
    (so the chip's spinner-or-dot indicator can re-render even when no
    content arrived), AND the retry counter (so a collapsed retry on
    an existing group triggers a chip re-render).
    """
    last_len = len(group.segments[-1].text) if group.segments else 0
    return (
        len(group.segments),
        last_len,
        group.model or "",
        group.pending,
        group.retries,
    )


class TranscriptWidget(VerticalScroll):
    """Scrollable list of message + tool-call widgets in arrival order."""

    DEFAULT_CSS = """
    TranscriptWidget {
        height: 1fr;
        /* Hide the scrollbar gutter so transcript content reaches the
         * right edge. Wheel + keyboard scrolling still work; the
         * scrollbar just doesn't reserve a column. */
        scrollbar-size: 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Map item identity → (widget, fingerprint). Both message and
        # tool-call widgets update in place; the fingerprint just
        # detects whether anything changed so we know to nudge the
        # auto-scroll.
        self._entries: dict[str, tuple[Widget, object]] = {}
        # Single pending scroll timer — restarted on each content
        # change so a burst of notifications coalesces into one
        # animated scroll (see _SCROLL_DEBOUNCE_SECONDS).
        self._scroll_timer: Timer | None = None
        # Generation token. Textual's set_timer queues callbacks via
        # call_next, so a timer's callback may already be in the queue
        # by the time .stop() runs — and stop() doesn't dequeue
        # already-queued callbacks. The generation captured in each
        # timer's closure lets the callback no-op when it's no longer
        # the current schedule, even if it managed to fire.
        self._scroll_generation = 0
        # scroll_y captured at debounce schedule time. When the
        # debounce fires we compare the current scroll_y to this — a
        # significant drop means the user scrolled up during the
        # debounce window, and we should NOT pull them back to the
        # bottom.
        self._scroll_y_when_scheduled = 0.0
        # max_scroll_y captured at animation kickoff. The on_complete
        # settle callback compares the landing scroll_y to this
        # target: at-or-near target means "we landed cleanly, check
        # for further content growth"; well below target means "user
        # pulled away during the animation, don't chase."
        self._scroll_target = 0.0

    def refresh_from(self, state: SessionState) -> None:
        """Sync mounted widgets to ``state.items`` order + content."""
        at_bottom = self._is_at_bottom()
        existing_keys = set(self._entries.keys())
        seen_keys: set[str] = set()
        content_changed = False

        for item in state.items:
            key = self._key_for(item)
            seen_keys.add(key)
            # ``defer_body``: terminal tool cards hold their body while
            # any sibling is still actively running. Without this gate,
            # parallel tool calls would stream completed results in one
            # at a time, pulling the operator's eye away from the
            # cards that are still pending. Computed per-item so the
            # transition of *another* tool to terminal causes this
            # item's fingerprint to flip → re-render → un-defer.
            defer_body = self._compute_defer_body(item, state)
            entry = self._entries.get(key)
            if entry is None:
                widget = self._build_widget(item, state, defer_body=defer_body)
                self._entries[key] = (widget, self._fingerprint(item, defer_body))
                self.mount(widget)
                content_changed = True
                continue
            widget, old_fp = entry
            new_fp = self._fingerprint(item, defer_body)
            if isinstance(item, ToolCallState) and isinstance(widget, ToolCallWidget):
                # Gate on fingerprint change — the comprehensive
                # tool-call fingerprint (status + content + raw_input
                # + defer_body) catches every visible mutation, so the
                # widget only re-renders when something actually
                # changed. Mirrors the message branch below.
                if old_fp != new_fp:
                    widget.update_state(item, defer_body=defer_body)
                    self._entries[key] = (widget, new_fp)
                    content_changed = True
            elif isinstance(item, MessageGroup) and isinstance(widget, MessageWidget):
                # IN-PLACE update — extends the last segment or mounts
                # new segments rather than tearing the bubble down.
                # Avoids the visible flash a full remount would cause
                # on every streaming chunk.
                if old_fp != new_fp:
                    widget.update_state(item)
                    self._entries[key] = (widget, new_fp)
                    content_changed = True

        for stale in existing_keys - seen_keys:
            entry = self._entries.pop(stale, None)
            if entry is not None:
                entry[0].remove()

        if content_changed and at_bottom:
            self._schedule_scroll_to_end()

    @staticmethod
    def _compute_defer_body(
        item: MessageGroup | ToolCallState | ScoreChip | EventChip,
        state: SessionState,
    ) -> bool:
        """Whether ``item``'s body should be held back this refresh.

        Gate fires while ``item`` is part of an unresolved parallel
        batch: ``item.parallel_batch_id`` is set AND some other member
        of *that same batch* is still in_progress. Covers BOTH the
        call-view (input preview, e.g. the bash command line, the
        ``lookup ACME`` markdown a custom viewer emits at call time)
        and the terminal result body — under parallel execution we
        want every card collapsed to its single-line header so no one
        tool juts out and pulls the eye off the in-flight set.

        ``parallel_batch_id`` is sticky: once a tool has been tagged
        with a batch id it keeps it for the rest of the session. So
        the last tool of a 3-call batch stays deferred even when its
        siblings have finished but it is still itself running — its
        own in_progress status, with its batch id, keeps the gate
        active. The reveal fires all-at-once when the last batch
        member transitions to terminal: that refresh flips
        ``defer_body`` to False for every held card in one pass,
        mounting bodies in declared order.

        Scoping by batch id (rather than a session-wide "any tagged
        tool still in-progress" sweep) means a later parallel batch
        does NOT pull an earlier, already-settled batch's bodies back
        into deferral.

        A solo tool never gets tagged with a batch id and never
        defers — same fast-path as before the gate existed.
        """
        if not isinstance(item, ToolCallState):
            return False
        if item.parallel_batch_id is None:
            return False
        return any(
            tc.parallel_batch_id == item.parallel_batch_id
            and tc.status == "in_progress"
            for tc in state._tool_calls_by_id.values()
        )

    def _schedule_scroll_to_end(self) -> None:
        """Coalesce rapid content changes into one debounced animated scroll.

        Each call cancels any pending timer and starts a new one —
        only when notifications stop arriving for the debounce window
        does the actual ``scroll_end`` fire. Prevents back-to-back
        animations (which the eye reads as a "snap" between legs).
        """
        self._scroll_y_when_scheduled = self.scroll_y
        if self._scroll_timer is not None:
            self._scroll_timer.stop()
        self._scroll_generation += 1
        generation = self._scroll_generation
        self._scroll_timer = self.set_timer(
            _SCROLL_DEBOUNCE_SECONDS,
            lambda: self._on_debounce_fired(generation),
        )

    def _on_debounce_fired(self, generation: int) -> None:
        """Debounce timer fired — start the animation iff still current.

        Guards against two cases the reviewer flagged:
        - **Stale callback**: a later ``_schedule_scroll_to_end`` may
          have superseded us by the time ``call_next`` actually runs
          this callback. ``generation != self._scroll_generation``
          catches it; the newer timer (or its descendants) will fire
          the scroll.
        - **User pulled away during debounce**: if the user manually
          scrolled up while we were waiting, ``scroll_y`` will have
          dropped significantly below where it was when we
          scheduled. Don't pull them back.
        """
        if generation != self._scroll_generation:
            return
        self._scroll_timer = None
        if self.scroll_y < self._scroll_y_when_scheduled - _USER_SCROLL_AWAY_TOLERANCE:
            return
        self._start_animated_scroll()

    def _start_animated_scroll(self) -> None:
        """Kick off the animated glide; capture target so settle can chase."""
        self._scroll_target = self.max_scroll_y
        self.scroll_end(
            animate=True,
            duration=_SCROLL_ANIMATE_SECONDS,
            easing="out_cubic",
            on_complete=self._on_scroll_settled,
        )

    def _on_scroll_settled(self) -> None:
        """Post-animation: chase the bottom if content grew; respect user pullaway.

        ``on_complete`` fires when the animation finishes (or is
        interrupted). Three outcomes, in order:

        1. **User pulled away**: ``scroll_y`` is well below
           ``_scroll_target`` — they scrolled up during the
           animation. Don't fight them.
        2. **Strictly at the bottom** (within one row): the chase is
           done.
        3. **Content grew during the animation**: ``scroll_y``
           reached the old target but ``max_scroll_y`` has advanced
           past it. Scroll again — no debounce, we're past the
           streaming burst. Loop converges as soon as one animation
           completes without further growth.

        This is the load-bearing guarantee that the view eventually
        lands at ``max_scroll_y``. It depends only on the
        animation-actually-completed signal, never on timer ordering.
        """
        if self.scroll_y < self._scroll_target - _USER_SCROLL_AWAY_TOLERANCE:
            return
        # A new debounced scroll has been scheduled in the meantime —
        # let it handle the next step rather than racing it.
        if self._scroll_timer is not None:
            return
        if self.scroll_y >= self.max_scroll_y - 1:
            return
        self._start_animated_scroll()

    @staticmethod
    def _fingerprint(
        item: MessageGroup | ToolCallState | ScoreChip | EventChip,
        defer_body: bool = False,
    ) -> object:
        if isinstance(item, MessageGroup):
            return _message_fingerprint(item)
        if isinstance(item, ScoreChip):
            # Score chips are immutable once mounted — the fingerprint
            # only needs to identify the chip, not detect changes.
            return item.chip_id
        if isinstance(item, EventChip):
            # Event chips are likewise immutable once mounted (no
            # streaming update path for SampleLimit/Error/Compaction/
            # Info events — each fires once and terminates).
            return item.chip_id
        # Comprehensive tool-call fingerprint (status + title + kind +
        # content + raw_input) — not just status — so the auto-scroll
        # decision tracks live-tail tool output. ``defer_body`` rides
        # along so a flip of the deferral gate (caused by a *sibling*
        # tool transitioning to terminal) is seen as a change here and
        # routes through ``update_state`` to mount the held-back body.
        return (tool_state_fingerprint(item), defer_body)

    def _build_widget(
        self,
        item: MessageGroup | ToolCallState | ScoreChip | EventChip,
        state: SessionState,
        *,
        defer_body: bool = False,
    ) -> Widget:
        if isinstance(item, MessageGroup):
            return MessageWidget(item, current_model=state.current_model)
        if isinstance(item, ScoreChip):
            return ScoreChipWidget(item)
        if isinstance(item, EventChip):
            return EventChipWidget(item)
        return ToolCallWidget(item, defer_body=defer_body)

    @staticmethod
    def _key_for(item: MessageGroup | ToolCallState | ScoreChip | EventChip) -> str:
        if isinstance(item, MessageGroup):
            return f"msg:{item.message_id}"
        if isinstance(item, ScoreChip):
            return f"score:{item.chip_id}"
        if isinstance(item, EventChip):
            return f"event:{item.chip_id}"
        return f"tool:{item.tool_call_id}"

    def _is_at_bottom(self) -> bool:
        """Generous "is the user following the bottom?" check.

        Uses :data:`_AT_BOTTOM_TOLERANCE` rows of slack so the
        auto-follow path keeps firing when we're a few rows short of
        max_scroll_y — typical mid-animation, or right after a chip
        widget mounts and pushes max_scroll_y down by its full
        height. Exactness lives in ``_on_scroll_settled``'s chase
        loop, not here.
        """
        try:
            return self.scroll_y >= self.max_scroll_y - _AT_BOTTOM_TOLERANCE
        except Exception:
            return True

    def tick_inflight_durations(self) -> None:
        """Nudge in-flight tool cards + empty message spinners.

        Called from the SessionScreen's periodic timer. Terminal tool
        cards no-op inside :meth:`ToolCallWidget.tick_duration`, and
        message widgets that already have content no-op inside
        :meth:`MessageWidget.tick_spinner` — so this is cheap once
        everything's done animating.
        """
        for entry in self._entries.values():
            widget, _ = entry
            if isinstance(widget, ToolCallWidget):
                widget.tick_duration()
            elif isinstance(widget, MessageWidget):
                widget.tick_spinner()
            elif isinstance(widget, ScoreChipWidget):
                widget.tick_spinner()
