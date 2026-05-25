"""Inline elicitation card.

Rendered into the session screen while
:attr:`~inspect_ai.agent._acp.tui.state.SessionState.pending_elicitation`
is set; unmounts as soon as the operator resolves it (or one of the
session cancel paths drops it).

The card extends the shared :class:`InlineRequestCard` primitive
(see :mod:`.inline_request_card`) — the outer bordered Vertical,
bold header, body, and compact-button actions row all come from
there. This file only fills in the elicitation-kind body
(:class:`ElicitationForm`) and the Submit / Decline action pair.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Button, Input

from inspect_ai._util.textual.form import ElicitationForm
from inspect_ai.agent._acp.tui.state import (
    ElicitationAction,
    PendingElicitation,
)

from .inline_request_card import InlineRequestCard


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


class _ElicitationCard(InlineRequestCard):
    """Inline form card rendered while an elicitation is pending.

    The screen mounts at most one of these (the agent loop issues
    one ``ask_user`` at a time). Submitted values flow back to the
    JSON-RPC handler via the :class:`ElicitationDecisionRequested`
    bubble — see the message's docstring.
    """

    _SUBMIT_ID = "submit-elicitation"
    _DECLINE_ID = "decline-elicitation"

    DEFAULT_CSS = """
    _ElicitationCard ElicitationForm {
        height: auto;
        max-height: 16;
    }
    /* Two sources contribute to the visible gap between the form
     * and the buttons: ElicitationForm's per-field
     * ``FieldRow { margin-bottom: 1 }`` (which fires even on the
     * last row, since the form was designed for multi-field
     * dialogs) and the base class's
     * ``#request-actions { margin-top: 1 }``. With a typical
     * single-question schema both fire and the result reads as a
     * stray 2-row hole. Zero both out here — approval / cancel
     * cards have no body and still need the actions breathing
     * room, so the override is scoped to ``_ElicitationCard`` and
     * does not leak. */
    _ElicitationCard FieldRow:last-of-type {
        margin-bottom: 0;
    }
    _ElicitationCard #request-actions {
        margin-top: 0;
    }
    """

    def __init__(
        self,
        *,
        message: str,
        schema: Any,
    ) -> None:
        super().__init__()
        self._message = message
        self._schema = schema
        # Held for ``on_mount`` so focus lands on the first form field
        # — the base's first-focusable walk would land on the
        # ElicitationForm's first input anyway, but going through
        # ``ElicitationForm.focus_first`` is more deliberate (it
        # knows how to skip over decorative widgets inside the form).
        self._form: ElicitationForm | None = None

    @classmethod
    def from_pending(cls, pending: PendingElicitation) -> "_ElicitationCard":
        """Build a card from a parked :class:`PendingElicitation`.

        Convenience for the session screen so the mount site doesn't
        have to know the card's constructor shape. Pins the
        :class:`PendingElicitation` identity on the card's
        :attr:`request` slot (base-class attribute) so the screen
        can detect a stale match and replace.
        """
        card = cls(message=pending.message, schema=pending.requested_schema)
        card.request = pending
        return card

    @property
    def pending(self) -> PendingElicitation | None:
        """Back-compat accessor for the parked elicitation identity.

        New code should read ``card.request`` directly (the base
        class slot); this property exists so tests written against
        the Phase 6a name keep passing without churn. Returns
        whatever was set via :meth:`from_pending`.
        """
        if isinstance(self.request, PendingElicitation):
            return self.request
        return None

    @property
    def header_text(self) -> str:
        return self._message

    def compose_body(self) -> ComposeResult:
        form = ElicitationForm(self._schema)
        self._form = form
        yield form

    def compose_actions(self) -> ComposeResult:
        yield Button(
            "Submit",
            id=self._SUBMIT_ID,
            variant="primary",
            compact=True,
            tooltip="Submit the answer.",
        )
        yield Button(
            "Decline",
            id=self._DECLINE_ID,
            compact=True,
            tooltip="Decline to answer.",
        )

    def on_mount(self) -> None:
        # Override the base's first-focusable walk: go through
        # ``ElicitationForm.focus_first`` so we land on a real form
        # input even if the form starts with decorative widgets.
        #
        # Defer one refresh cycle: at on_mount time the form's
        # FieldRow children have been yielded and their direct
        # children (Input / Select / etc.) appear in the widget
        # tree, but layout hasn't run yet and Textual's
        # ``focus()`` is a no-op against a widget that isn't yet
        # part of a laid-out screen. ``call_after_refresh`` runs
        # the call after the next refresh pass, when the whole
        # subtree is live and focusable. Mirrors the
        # "Approval / cancel auto-focus a button on mount" UX —
        # the elicitation flavour just targets the first form
        # input rather than the first button.
        if self._form is not None:
            self.call_after_refresh(self._form.focus_first)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter on a form Input → advance to next empty required, or submit.

        Textual's :class:`Input` consumes Enter and emits
        :class:`Input.Submitted`, stopping the keypress event
        before the screen-level ``Binding("enter", action_submit)``
        runs. So this handler is the canonical Enter dispatch
        while the elicitation card has focus on a form input —
        no need for a screen-level priority binding.

        Multi-field UX (chose "advance, then submit"):

        - If a later required field is still empty, focus it and
          do NOT submit. Operators can fill multi-field forms by
          typing + Enter through each row, the same Tab-then-Enter
          flow they expect from web forms.
        - Otherwise (all required fields filled, or this is the
          only field), call :meth:`_submit` — the same path the
          Submit button click takes. Validation errors short-
          circuit submit and surface inline.
        """
        event.stop()
        form = self._form
        if form is None:
            return
        if not form.focus_next_empty_required(after=event.input):
            self._submit()

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
