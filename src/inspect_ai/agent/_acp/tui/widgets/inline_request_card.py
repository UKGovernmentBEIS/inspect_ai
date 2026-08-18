"""Inline-card primitive for parked human-in-the-loop requests.

Three concrete request kinds reuse this shape:

- :class:`_ElicitationCard` — `ask_user` / form prompt (agent-driven).
- :class:`_ApprovalCard` — tool-call approval (agent-driven).
- :class:`_CancelCard` — operator-initiated sample cancel (operator-driven).

All three render the same way: an outer bordered :class:`Vertical`
mounted inline below the transcript, a bold header, a body the
subclass fills in, and a row of compact-style action buttons. The
session screen's apply-loop compares :attr:`request` against the
matching state slot and remounts on divergence (the stale-pending
case Phase 6a hit for elicitation, generalised here).

The compact-button styling mirrors the running-sample header's
Interrupt button (`_display/textual/widgets/samples.py`):
single-line height, tight padding, no fixed min-width. Pair with
``Button(..., compact=True)`` in subclass ``compose_actions``.
"""

from __future__ import annotations

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

_HEADER_CLASS = "request-header"
_ACTIONS_ID = "request-actions"


class InlineRequestCard(Vertical):
    """Base class for inline parked-request cards.

    Subclass contract:

    - Override :attr:`header_text` to supply the bold heading.
    - Override :meth:`compose_body` to yield the request-kind-specific
      body widgets (form, tool-call summary, plain prompt …).
    - Override :meth:`compose_actions` to yield the action buttons
      (typically compact :class:`Button` instances).
    - Set :attr:`request` to the parked-request identity so the
      screen's apply-loop can detect stale mounts. Production code
      goes through a ``from_*`` classmethod that sets it; unit-test
      construction may leave it ``None``.
    """

    DEFAULT_CSS = """
    InlineRequestCard {
        height: auto;
        margin: 1 2 1 2;
        /* No top padding — the ``tall`` border already provides
         * visual separation, and the prior ``1`` looked like an
         * empty row sat between the border and the header. */
        padding: 0 1 0 1;
        border: tall $accent 55%;
    }
    InlineRequestCard .request-header {
        text-style: bold;
        margin-bottom: 1;
    }
    InlineRequestCard #request-actions {
        height: auto;
        margin-top: 1;
    }
    InlineRequestCard #request-actions Button {
        min-width: 0;
        width: auto;
        height: auto;
        margin: 0 1 0 0;
        padding: 0 1;
    }
    InlineRequestCard #request-actions Button.kind-allow-once,
    InlineRequestCard #request-actions Button.kind-allow-always {
        color: $success;
    }
    InlineRequestCard #request-actions Button.kind-reject-once {
        color: $warning;
    }
    InlineRequestCard #request-actions Button.kind-reject-always {
        color: $error;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Set by from_* classmethods on subclasses; the session
        # screen compares ``existing.request is pending`` to detect
        # stale mounts when a fresh request swaps in before the old
        # card unmounts. ``None`` for direct constructor use (unit
        # tests).
        self.request: object | None = None

    @property
    def header_text(self) -> RenderableType:
        """The bold header content. Subclasses must override.

        Return a plain ``str`` for a single-style header (the base
        applies bold via the ``.request-header`` CSS class), or a
        Rich :class:`~rich.text.Text` with embedded styles for
        mixed-emphasis headers (e.g. the approval card's
        ``"Tool Approval Requested"`` + dim tool name).
        """
        raise NotImplementedError

    def compose_body(self) -> ComposeResult:
        """Yield body widgets between the header and the actions row.

        Subclasses override to render their request-kind-specific
        body (e.g. an :class:`ElicitationForm`, a tool-call summary,
        or a plain prompt sentence).
        """
        raise NotImplementedError
        yield  # pragma: no cover — make this a generator function

    def compose_actions(self) -> ComposeResult:
        """Yield the action affordances, typically compact Buttons.

        Subclasses override to render their request-kind-specific
        actions. Buttons should pass ``compact=True`` and carry the
        ``kind-...`` class when they want the success / warning /
        error colour vocabulary defined in this class's CSS.
        """
        raise NotImplementedError
        yield  # pragma: no cover — make this a generator function

    def compose(self) -> ComposeResult:
        # ``markup=False`` keeps the elicitation card's free-form
        # ``pending.message`` from being interpreted as Rich markup
        # (the message comes straight from the agent). Subclasses
        # that want mixed styling return a pre-built Rich
        # :class:`~rich.text.Text` from :attr:`header_text` — Static
        # passes Text instances through unmodified regardless of the
        # ``markup`` flag.
        yield Static(self.header_text, classes=_HEADER_CLASS, markup=False)
        yield from self.compose_body()
        with Horizontal(id=_ACTIONS_ID):
            yield from self.compose_actions()

    def on_mount(self) -> None:
        """Focus the first focusable descendant on mount.

        Same rationale as the previous elicitation-card on_mount:
        focus landing on the actions row would let an early Space
        keypress trigger a button before the operator has read the
        card. Prefer body widgets (form fields, the tool-call
        summary) over the actions row; subclasses can override if a
        more specific target makes sense.
        """
        for widget in self.query("*"):
            if widget.focusable:
                widget.focus()
                return
