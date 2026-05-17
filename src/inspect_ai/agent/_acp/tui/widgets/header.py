"""One-row headers — app title + (optionally) session meta + connection.

Two widgets share the same tinted band + ``inspect acp`` left-rail
treatment so the picker and session screens read as part of one
chrome:

- :class:`AppHeaderWidget` — title only, used by the picker.
- :class:`SessionHeaderWidget` — title + task/sample/epoch/agent/tokens
  identifiers + connection indicator, used while attached to a session.

Labels are dim provenance; values render in the default text colour
so the eye lands on the identifying VALUES first and the labels
second. Mirrors the same hierarchy used in the assistant chip
("assistant · gpt-5") — labels recede, values pop.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from ..client import SessionRow
from ..picker_screen import _format_tokens
from ..state import UsageState


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
    SessionHeaderWidget #conn-indicator { width: auto; }
    SessionHeaderWidget #conn-indicator.up { color: $success; }
    SessionHeaderWidget #conn-indicator.down { color: $error; }
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
            yield Static("● connected", id="conn-indicator", classes="up", markup=False)

    def _meta_markup(self) -> str:
        # Labels are dim provenance; values render in the default
        # colour so the eye lands on the identifying VALUE first.
        # Same hierarchy as the assistant chip's "assistant · model"
        # treatment — uniform across the screen.
        row = self._row
        agent = row.agent_name or "—"
        task = _short_task_name(row.task)
        parts = [
            f"[dim]task:[/dim] {task}",
            f"[dim]sample:[/dim] {row.sample_id}",
            f"[dim]epoch[/dim] {row.epoch}",
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
        return f"[dim]tokens[/dim] {_format_tokens(u.used)}"

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
        except Exception:
            pass

    def set_connected(self, connected: bool) -> None:
        """Flip the connection indicator (sage when up, rust when down)."""
        try:
            indicator = self.query_one("#conn-indicator", Static)
        except Exception:
            return
        if connected:
            indicator.update("● connected")
            indicator.remove_class("down")
            indicator.add_class("up")
        else:
            indicator.update("○ disconnected")
            indicator.remove_class("up")
            indicator.add_class("down")
