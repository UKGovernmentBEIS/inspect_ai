"""Status row widget — pill + state-dependent chips.

Reads a :class:`SessionState` snapshot via :meth:`StatusRowWidget.refresh_from`
and re-renders. The Phase-2 subset of the design-doc state machine:

- ``Awaiting input`` (sage) — default resting
- ``Generating`` (amber) — recent chunk activity within the quiescence window
- ``Calling tools`` (teal) — at least one in-flight tool

Phase 5 will add the terminal states (Scoring / Completed / Errored /
Interrupted). The CSS classes are pre-allocated so adding them later is
just a label update.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from .._picker_screen import _format_tokens
from .._state import SessionState, StatusState

_PILL_LABEL: dict[StatusState, str] = {
    StatusState.AWAITING_INPUT: "Awaiting input",
    StatusState.GENERATING: "Generating",
    StatusState.CALLING_TOOLS: "Calling tools",
}

_PILL_CLASS: dict[StatusState, str] = {
    StatusState.AWAITING_INPUT: "sage",
    StatusState.GENERATING: "amber",
    StatusState.CALLING_TOOLS: "teal",
}


class StatusRowWidget(Widget):
    """Pill + chips strip just under the meta row."""

    DEFAULT_CSS = """
    StatusRowWidget {
        height: auto;
        padding: 0 2 1 2;
    }
    StatusRowWidget Horizontal { height: auto; }
    StatusRowWidget .pill {
        padding: 0 1;
        margin-right: 2;
        text-style: bold;
    }
    StatusRowWidget .pill.sage { background: $success 25%; color: $success; }
    StatusRowWidget .pill.amber { background: $warning 25%; color: $warning; }
    StatusRowWidget .pill.teal { background: $primary 25%; color: $primary; }
    StatusRowWidget .chip {
        color: $text-muted;
        margin-right: 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._last_state: StatusState = StatusState.AWAITING_INPUT

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(
                self._pill_text(self._last_state), classes="pill sage", id="pill"
            )
            yield Static("", classes="chip", id="chip-model")
            yield Static("", classes="chip", id="chip-tokens")
            yield Static("", classes="chip", id="chip-tools")

    def refresh_from(self, state: SessionState) -> None:
        """Re-render the row from the current SessionState snapshot."""
        try:
            pill = self.query_one("#pill", Static)
            chip_model = self.query_one("#chip-model", Static)
            chip_tokens = self.query_one("#chip-tokens", Static)
            chip_tools = self.query_one("#chip-tools", Static)
        except Exception:
            # Not mounted yet — first compose() call hasn't fired.
            return

        status = state.status
        pill.update(self._pill_text(status))
        # Swap the pill's colour class only when the state changes —
        # avoids needless DOM churn on every refresh tick.
        if status != self._last_state:
            for cls in _PILL_CLASS.values():
                pill.remove_class(cls)
            pill.add_class(_PILL_CLASS[status])
            self._last_state = status

        chip_model.update(self._model_chip(state.current_model))
        chip_tokens.update(self._tokens_chip(state))
        chip_tools.update(self._tools_chip(state.tools_in_flight))

    @staticmethod
    def _pill_text(status: StatusState) -> str:
        return _PILL_LABEL[status]

    @staticmethod
    def _model_chip(model: str | None) -> str:
        return f"model {model}" if model else ""

    @staticmethod
    def _tokens_chip(state: SessionState) -> str:
        u = state.usage
        if u is None:
            return ""
        if u.size > 0:
            return f"tokens {_format_tokens(u.used)} / {_format_tokens(u.size)}"
        return f"tokens {_format_tokens(u.used)}"

    @staticmethod
    def _tools_chip(n: int) -> str:
        if n <= 0:
            return ""
        return f"{n} tool{'s' if n != 1 else ''} in flight"
