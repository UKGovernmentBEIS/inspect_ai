"""Generic composer-area prompt option button.

Reusable focusable + clickable button used by the composer-area
prompt bars (:class:`_ApprovalBar`, :class:`_CancelSampleBar`).
Renders as ``[ underlined-letter ] label`` — the same terminal-prompt
aesthetic the approval bar pioneered, generalised so the cancel-sample
bar (and future composer-area prompts) can share the look + keyboard
ergonomics without duplicating the widget.

Posts :class:`_PromptOption.Pressed` on mouse click OR ``Enter`` /
``Space``; the parent bar interprets the carried ``action_id`` and
translates it into whatever wire / state mutation it needs.

Implementation notes:

- ``Static``, not ``Button``. Textual's ``Button`` ships with a heavy
  ``.-style-default`` ruleset that a per-widget DEFAULT_CSS can't
  cleanly defeat. ``Static`` renders as plain coloured text, which
  matches the bar's terminal-prompt look.
- ``can_focus = True`` puts the widget in the Tab chain so keyboard
  users can reach it without bare-letter shortcuts.
- ``enter`` / ``space`` bindings let a focused option fire its own
  press without help from a screen-level submit delegation.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.events import Click
from textual.message import Message
from textual.widgets import Static


class _PromptOption(Static, can_focus=True):
    """One clickable, focusable, Enter-activatable option in a prompt bar.

    Each instance carries:

    - ``action_id``: identifier returned in the ``Pressed`` event so
      the parent bar can route to the right handler.
    - ``key``: keyboard shortcut letter shown underlined in the label.
      The bare-letter binding itself is owned by the screen / bar (so
      the widget stays focus-agnostic); this is just the visible cue.
    - ``label``: human-readable text shown after ``[ k ]``.
    - ``kind``: CSS class suffix that drives the option's colour
      (``kind-allow-once``, ``kind-score``, etc.). Each bar defines
      its own colour vocabulary in its ``DEFAULT_CSS``.
    """

    DEFAULT_CSS = """
    _PromptOption {
        height: 1;
        width: auto;
        padding: 0 1;
        margin: 0 1 0 0;
        color: $foreground;
    }
    /* Focused option gets a subtle background highlight so the
     * operator can see which one Enter / mouse-down will hit. The
     * letter is always underlined; this adds the focus cue without
     * fighting the colour-by-kind scheme defined by each bar. */
    _PromptOption:focus {
        background: $boost;
    }
    """

    BINDINGS = [
        Binding("enter", "press", show=False),
        Binding("space", "press", show=False),
    ]

    class Pressed(Message, namespace="prompt_option"):
        """Emitted when the option fires (click or Enter / Space).

        Carries the option's ``action_id`` so the parent bar can route
        to the right handler. The bar (not the option) holds whatever
        race-protection state it needs — e.g. the approval bar
        validates the press against its ``_mounted_request_id`` and
        the live :meth:`SessionState.current_pending_tool_call_id` so
        a queued press that lands after the pending approval rotated
        doesn't accidentally apply to a different tool call.

        ``namespace="prompt_option"`` forces the receive-side handler
        name to ``on_prompt_option_pressed``. Without it Textual
        derives the name from ``_PromptOption.Pressed.__qualname__``
        and preserves the leading underscore on the class, producing
        ``on__prompt_option_pressed`` (double underscore) which is
        easy to typo-mismatch with the handler.
        """

        def __init__(self, action_id: str) -> None:
            super().__init__()
            self.action_id = action_id

    def __init__(
        self,
        *,
        action_id: str,
        key: str,
        label: str,
        kind: str,
        widget_id: str | None = None,
    ) -> None:
        rendered = Text.from_markup(f"\\[ [underline]{key}[/] ] {label}")
        super().__init__(rendered, id=widget_id)
        self._action_id = action_id
        self.add_class(f"kind-{kind.replace('_', '-')}")

    @property
    def action_id(self) -> str:
        return self._action_id

    def action_press(self) -> None:
        self.post_message(self.Pressed(self._action_id))

    def on_click(self, event: Click) -> None:
        self.post_message(self.Pressed(self._action_id))
        event.stop()
