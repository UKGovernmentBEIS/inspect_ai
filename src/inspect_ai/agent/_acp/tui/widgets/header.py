"""One-row headers — app title + (optionally) session meta + lifecycle.

Two widgets share the same tinted band + ``inspect acp`` left-rail
treatment so the picker and session screens read as part of one
chrome:

- :class:`AppHeaderWidget` — title only, used by the picker.
- :class:`SessionHeaderWidget` — title + task/sample/epoch/agent/tokens
  identifiers + a turn-lifecycle pill (running / interrupted /
  complete), used while attached to a session.

Labels are dim provenance; values render in the default text colour
so the eye lands on the identifying VALUES first and the labels
second. Mirrors the same hierarchy used in the assistant chip
("assistant · gpt-5") — labels recede, values pop.
"""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from ..client import SessionRow
from ..state import UsageState
from ._formatting import format_tokens

Lifecycle = Literal["idle", "running", "scoring", "interrupted", "approval", "complete"]

_LIFECYCLE_TEXT: dict[Lifecycle, str] = {
    # Glyphs picked so the *shape* alone carries state even before
    # colour registers: filled dot for live, slashed circle for
    # halted, check for done, warning triangle for "agent is blocked
    # on you". Colour styling lives in the CSS rules on
    # ``#lifecycle-indicator.<state>``. Idle has no text — the pill
    # goes invisible via the ``.idle`` rule so the chrome stays quiet
    # when nothing is happening.
    "idle": "",
    "running": "● running",
    # ``scoring`` reads as "still working but in a different phase" —
    # the agent loop is done and the post-agent scoring pass is the
    # foreground activity. Same dot glyph as ``running`` so it doesn't
    # read as a halt; distinct colour signals it as a different phase.
    "scoring": "● scoring",
    "interrupted": "⊘ interrupted",
    # ``approval`` reads as more urgent than ``running`` (the agent is
    # specifically waiting on the operator) — same warning colour as
    # ``interrupted`` since both are "an operator should look at this
    # now" states.
    "approval": "⚠ awaiting approval",
    "complete": "✓ complete",
}


def _short_task_name(name: str) -> str:
    """Strip everything up to and including the first ``/``.

    Inspect task names commonly look like ``inspect_harbor/terminal_bench_2_0``
    where the prefix is the suite and the suffix is the actual task.
    The suite is constant across rows and eats horizontal space the
    header can't afford — drop it so the operator sees the bit that
    actually distinguishes this run.
    """
    if "/" not in name:
        return name
    return name.split("/", 1)[1]


class AppHeaderWidget(Widget):
    """Slim tinted header — ``inspect acp`` only.

    Used by the picker (no session-specific meta to show yet) so the
    chrome reads as part of the same family as the session screen's
    header. Shares the visual treatment with :class:`SessionHeaderWidget`
    via duplicated CSS — kept small + standalone for clarity.
    """

    DEFAULT_CSS = """
    AppHeaderWidget {
        height: 1;
        padding: 0 2;
        background: $foreground 5%;
        margin-bottom: 1;
    }
    AppHeaderWidget .app-title {
        width: auto;
        color: $accent;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("inspect acp", classes="app-title", markup=False)


class SessionHeaderWidget(Widget):
    """One-row header — app name + meta identifiers + connection indicator."""

    DEFAULT_CSS = """
    SessionHeaderWidget {
        height: 1;
        padding: 0 2;
        background: $foreground 5%;
        /* Breathing room between the tinted header band and the
         * transcript below — without it the first message bucks up
         * against the header edge. Margin (not padding) so the band
         * itself stays 1 row tall. */
        margin-bottom: 1;
    }
    SessionHeaderWidget Horizontal { height: 1; }
    SessionHeaderWidget .app-title {
        width: auto;
        color: $accent;
        text-style: bold;
        padding-right: 3;
    }
    SessionHeaderWidget .meta {
        width: 1fr;
    }
    SessionHeaderWidget #lifecycle-indicator { width: auto; }
    SessionHeaderWidget #lifecycle-indicator.running { color: $success; }
    /* Scoring shares the blue ``$primary`` family with ``complete`` to
     * signal it as a post-agent phase, but distinct from the green
     * ``running`` and orange ``warning`` colours so the operator can
     * tell at a glance "we're past the agent loop now". */
    SessionHeaderWidget #lifecycle-indicator.scoring { color: $primary; }
    SessionHeaderWidget #lifecycle-indicator.interrupted { color: $warning; }
    /* Approval shares the warning colour with ``interrupted`` — both
     * are "operator attention needed" states and we want one visual
     * vocabulary for them. The glyph + text distinguish the cause. */
    SessionHeaderWidget #lifecycle-indicator.approval { color: $warning; }
    /* ``$primary`` is the blue brand token in Textual's default
     * dark theme; ``$accent`` rendered orange in practice and
     * clashed with the ``$warning``-orange interrupted state. */
    SessionHeaderWidget #lifecycle-indicator.complete { color: $primary; }
    /* Idle: hide entirely. Keeps the band quiet between turns. */
    SessionHeaderWidget #lifecycle-indicator.idle { display: none; }
    """

    def __init__(self, row: SessionRow) -> None:
        super().__init__()
        self._row = row
        self._usage: UsageState | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("inspect acp", classes="app-title", markup=False)
            yield Static(
                self._meta_markup(), classes="meta", id="meta-text", markup=True
            )
            # Lifecycle pill — starts as ``idle`` (no work yet) and
            # therefore hidden via the ``.idle`` rule.
            # ``SessionScreen._apply_state`` calls ``set_lifecycle`` on
            # every state notification to keep it in sync.
            yield Static(
                _LIFECYCLE_TEXT["idle"],
                id="lifecycle-indicator",
                classes="idle",
                markup=False,
            )

    def _meta_markup(self) -> str:
        # Labels are dim provenance; values render in the default
        # colour so the eye lands on the identifying VALUE first.
        # Same hierarchy as the assistant chip's "assistant · model"
        # treatment — uniform across the screen.
        row = self._row
        agent = row.agent_name or "—"
        task = _short_task_name(row.task)
        # ``sample/epoch`` fuses into one field — epoch is a sub-key of
        # the sample (each sample-epoch pair is its own session), so
        # ``sample: foo/1`` reads as one identifier instead of two
        # adjacent ones and frees a meta slot.
        parts = [
            f"[dim]task:[/dim] {task}",
            f"[dim]sample:[/dim] {row.sample_id}/{row.epoch}",
            f"[dim]agent:[/dim] {agent}",
        ]
        tokens = self._tokens_markup()
        if tokens:
            parts.append(tokens)
        return "   ".join(parts)

    def _tokens_markup(self) -> str:
        # Used-only — the context window denominator was visual noise
        # the operator didn't need at a glance (size is roughly model-
        # invariant and the running total is the bit that changes).
        u = self._usage
        if u is None:
            return ""
        return f"[dim]tokens[/dim] {format_tokens(u.used)}"

    def set_lifecycle(self, state: Lifecycle) -> None:
        """Reflect the latest turn lifecycle on the upper-right pill.

        Driven by ``SessionScreen._apply_state`` so the pill and the
        composer placeholder both read from the same
        :attr:`SessionState.lifecycle` derivation.
        """
        try:
            pill = self.query_one("#lifecycle-indicator", Static)
        except NoMatches:
            return
        for cls in (
            "idle",
            "running",
            "scoring",
            "interrupted",
            "approval",
            "complete",
        ):
            pill.remove_class(cls)
        pill.update(_LIFECYCLE_TEXT[state])
        pill.add_class(state)

    def set_usage(self, usage: UsageState | None) -> None:
        """Refresh the tokens chip from the latest UsageUpdate.

        Called from the SessionScreen on every state notification —
        cheap because we only re-render when the value actually
        changed.
        """
        if usage == self._usage:
            return
        self._usage = usage
        try:
            self.query_one("#meta-text", Static).update(self._meta_markup())
        except NoMatches:
            pass
