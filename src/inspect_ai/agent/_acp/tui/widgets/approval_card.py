"""Inline approval card.

Rendered into the session screen while
:meth:`~inspect_ai.agent._acp.tui.state.SessionState.current_pending_approval`
returns a non-None :class:`PendingApproval`. Replaces the
composer-row :class:`_ApprovalBar` from Phase 6a — the approval
prompt now lives inline below the transcript, alongside the
elicitation and cancel cards, sharing the
:class:`InlineRequestCard` primitive.

Action shortcuts: the screen still owns the bare-letter bindings
(``a`` / ``r`` / ``m`` / ``t`` / ``e``); the buttons here carry the
``approve-opt-<decision>`` id convention from
:mod:`.tool_call`, so the screen's existing id-based delegation in
``action_submit`` continues to dispatch to them with no further
plumbing.
"""

from __future__ import annotations

from acp.schema import PermissionOption
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Button

from inspect_ai.agent._acp.tui.state import PendingApproval

from .inline_request_card import InlineRequestCard
from .tool_call import _BUTTON_ID_PREFIX, ApprovalDecisionRequested

# Display labels for ACP option kinds. The wire layer (the
# ``human_approver`` shim) assigns labels to ``PermissionOption.name``
# but those don't carry the bare-letter underline used by the bar's
# rendering. We re-derive the label from the option_id so we can
# layer the shortcut underline ourselves via Rich markup; falls back
# to the wire label when the option_id is not in the canonical set.
_LABEL_OVERRIDES: dict[str, str] = {
    "approve": "Approve",
    "reject": "Reject",
    "modify": "Modify",
    "terminate": "Terminate",
    "escalate": "Escalate",
}


def _button_label(option: PermissionOption) -> Text:
    """Render the button label with the shortcut letter underlined.

    Example: ``"approve"`` renders as a Rich Text with the leading
    ``A`` underlined. Mirrors the look of the old ``_PromptOption``
    (which rendered as ``[ a ] approve`` via Static markup).

    The bare-letter shortcut binding itself is owned by the screen;
    this is purely the visible cue so the operator can see which key
    fires which option without consulting the footer.
    """
    label_text = _LABEL_OVERRIDES.get(option.option_id, option.name or option.option_id)
    if not label_text:
        return Text(option.option_id)
    first, rest = label_text[0], label_text[1:]
    text = Text()
    text.append(first, style="underline")
    text.append(rest)
    return text


class _ApprovalCard(InlineRequestCard):
    """Inline card rendered while a tool-call approval is pending.

    Header is a descriptive title of the call (e.g. ``"bash ls -la"``)
    so the operator can associate the card with the tool-call entry
    above it in the transcript without scrolling. No body — the
    tool-call card upstream already renders the view-content preview
    (context + call halves) via :class:`_ApprovalContent`; embedding
    it again here would duplicate the same content a few rows apart.
    """

    def __init__(self, pending: PendingApproval) -> None:
        super().__init__()
        self.request = pending
        self._pending = pending

    @classmethod
    def from_pending(cls, pending: PendingApproval) -> "_ApprovalCard":
        """Build a card for a parked :class:`PendingApproval`."""
        return cls(pending)

    @property
    def header_text(self) -> Text:
        """Two-tone header: ``"Tool Approval"`` + dim descriptive title.

        The dim suffix is ``call.title`` verbatim — already the
        descriptive form produced by :func:`descriptive_title`
        upstream in the human-approver shim (see
        ``approval/_human/acp.py``). We deliberately do NOT re-run
        ``descriptive_title`` here: passing the already-descriptive
        title back through as ``fn`` would hit the generic
        string-arg fallback and duplicate the argument summary
        (regression: the bug produced
        ``"dangerous_action rm -rf … rm -rf …"``).
        """
        title = self._pending.request.tool_call.title or "tool"
        text = Text("Tool Approval")
        text.append("  ")
        text.append(title, style="dim")
        return text

    def compose_body(self) -> ComposeResult:
        # No body: the tool-call card upstream already shows the
        # view-content preview. Mirrors the Phase 6a contract for
        # the approval bar (the bar carried only question + options).
        return
        yield  # pragma: no cover — make this a generator function

    def compose_actions(self) -> ComposeResult:
        for option in self._pending.request.options:
            yield Button(
                _button_label(option),
                id=f"{_BUTTON_ID_PREFIX}{option.option_id}",
                compact=True,
                classes=f"kind-{option.kind.replace('_', '-')}",
                tooltip=option.name or option.option_id,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Stop here so the screen doesn't see a raw Button.Pressed —
        # we re-emit the typed ApprovalDecisionRequested instead so
        # the screen handler stays the same as it was for the bar.
        event.stop()
        button_id = event.button.id or ""
        if not button_id.startswith(_BUTTON_ID_PREFIX):
            return
        option_id = button_id[len(_BUTTON_ID_PREFIX) :]
        tool_call_id = self._pending.request.tool_call.tool_call_id
        self.post_message(
            ApprovalDecisionRequested(
                tool_call_id=tool_call_id,
                option_id=option_id,
            )
        )
