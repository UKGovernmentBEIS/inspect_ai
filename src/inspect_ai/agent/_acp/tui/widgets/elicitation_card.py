"""Inline elicitation card — Phase 6a minimal version.

Rendered into the session screen while
:attr:`~inspect_ai.agent._acp.tui.state.SessionState.pending_elicitation`
is set; unmounts as soon as the operator resolves it (or one of the
session cancel paths drops it). Bare-minimum widget: a bold header
showing the elicitation's prompt, the shared
:class:`~inspect_ai._util.textual.form.ElicitationForm` body, and a
Submit / Decline button row.

Phase 6b will extract a reusable ``InlineRequestCard`` primitive
(approval + cancel migrate onto it); for now this widget is
elicitation-specific so we ship the wire path end-to-end without
locking in an abstraction that we haven't yet validated against
the other request kinds.
"""

from __future__ import annotations

from typing import Any

from acp.schema import ElicitationSchema
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

from inspect_ai._util.textual.form import ElicitationForm
from inspect_ai.agent._acp.tui.state import (
    ElicitationAction,
    PendingElicitation,
)


class ElicitationDecisionRequested(Message):
    """Bubbles up from :class:`_ElicitationCard` when the operator decides.

    The session screen listens for this and calls
    :meth:`SessionState.resolve_elicitation` with the same fields,
    which fires the pending event so the parked JSON-RPC handler
    sends the wire response.

    ``content`` is set only when ``action == "accept"`` — the form
    payload validated against the elicitation's schema. ``decline``
    and ``cancel`` carry no content (matching the ACP wire shape).
    """

    def __init__(
        self,
        action: ElicitationAction,
        content: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.action = action
        self.content = content


class _ElicitationCard(Vertical):
    """Inline form card rendered while an elicitation is pending.

    The screen mounts at most one of these (the agent loop issues
    one ``ask_user`` at a time). Submitted values flow back to the
    JSON-RPC handler via the :class:`ElicitationDecisionRequested`
    bubble — see the message's docstring.
    """

    _SUBMIT_ID = "submit-elicitation"
    _DECLINE_ID = "decline-elicitation"

    DEFAULT_CSS = """
    _ElicitationCard {
        height: auto;
        margin: 1 2 1 2;
        padding: 1 1 0 1;
        border: tall $accent 55%;
    }
    _ElicitationCard .elicitation-prompt {
        text-style: bold;
        margin-bottom: 1;
    }
    _ElicitationCard ElicitationForm {
        height: auto;
        max-height: 16;
    }
    _ElicitationCard #elicitation-actions {
        height: auto;
        margin-top: 1;
    }
    _ElicitationCard #elicitation-actions Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        *,
        message: str,
        schema: ElicitationSchema,
    ) -> None:
        super().__init__()
        self._message = message
        self._schema = schema
        # Held for ``on_mount`` so focus lands on the first field — same
        # rationale as ``QuestionInputPanel.on_questions_changed`` (focus
        # on Submit would let Space submit an empty form).
        self._form: ElicitationForm | None = None
        # Identity of the ``PendingElicitation`` this card represents,
        # set by :meth:`from_pending`. The session screen's apply-loop
        # compares this against ``state.pending_elicitation`` and
        # remounts when they diverge — covers the case where a second
        # ``ask_user`` arrives before the prior card has unmounted
        # (without this, the screen would keep the stale prompt /
        # schema mounted while submissions resolved the new pending).
        # ``None`` for cards built directly via the constructor (unit
        # tests); production code always goes through ``from_pending``.
        self.pending: PendingElicitation | None = None

    @classmethod
    def from_pending(cls, pending: PendingElicitation) -> "_ElicitationCard":
        """Build a card from a parked :class:`PendingElicitation`.

        Convenience for the session screen so the mount site doesn't
        have to know the card's constructor shape. Pins the
        :class:`PendingElicitation` identity on the card so the screen
        can detect a stale match and replace.
        """
        card = cls(message=pending.message, schema=pending.requested_schema)
        card.pending = pending
        return card

    def compose(self) -> ComposeResult:
        yield Static(self._message, classes="elicitation-prompt", markup=False)
        form = ElicitationForm(self._schema)
        self._form = form
        yield form
        with Horizontal(id="elicitation-actions"):
            yield Button(
                "Submit",
                id=self._SUBMIT_ID,
                variant="primary",
                tooltip="Submit the answer.",
            )
            yield Button(
                "Decline",
                id=self._DECLINE_ID,
                tooltip="Decline to answer.",
            )

    def on_mount(self) -> None:
        # Focus the first form field — see QuestionInputPanel for the
        # rationale (focus on Submit would let an early Space activate
        # the button and submit an empty form).
        if self._form is not None:
            self._form.focus_first()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Stop here so the screen doesn't see a generic Button.Pressed —
        # the screen handles our typed ElicitationDecisionRequested
        # message instead.
        event.stop()
        if event.button.id == self._SUBMIT_ID:
            self._submit()
        elif event.button.id == self._DECLINE_ID:
            self.post_message(ElicitationDecisionRequested(action="decline"))

    def _submit(self) -> None:
        form = self._form
        if form is None:  # defensive — compose hasn't run yet
            return
        values, errors = form.collect()
        if errors:
            form.show_errors(errors)
            return
        form.clear_errors()
        # values is non-None when errors is empty (per ElicitationForm.collect
        # contract); pass {} rather than None for type safety.
        self.post_message(
            ElicitationDecisionRequested(action="accept", content=values or {})
        )
