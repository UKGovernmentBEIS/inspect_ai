"""Textual harness tests for the Phase 6a inline elicitation card.

Mirrors ``tests/input/test_input_panel.py``: each test mounts the
:class:`_ElicitationCard` inside a minimal :class:`App` and drives
clicks + form input through the real event loop. Bubble messages
posted by the card are captured by the host App so we can assert
the exact wire-relevant data the session screen would see.
"""

from __future__ import annotations

import pytest
from acp.schema import (
    ElicitationBooleanPropertySchema,
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Button, Checkbox, Input

from inspect_ai._util.textual.form import ElicitationForm
from inspect_ai.agent._acp.tui.widgets.elicitation_card import (
    ElicitationDecisionRequested,
    _ElicitationCard,
)


def _schema(*, required: bool = True) -> ElicitationSchema:
    # ``agree`` is given a default=False so it renders as a Checkbox
    # rather than a tristate Select — the form widget switches to
    # Select for optional booleans with no default (see
    # ``_compose_boolean``). Tests want a deterministic widget mix.
    return ElicitationSchema(
        properties={
            "answer": ElicitationStringPropertySchema(type="string", title="Answer"),
            "agree": ElicitationBooleanPropertySchema(
                type="boolean", title="Agree?", default=False
            ),
        },
        required=["answer"] if required else [],
    )


class _CardApp(App[None]):
    """Minimal host for a single :class:`_ElicitationCard`.

    Captures the :class:`ElicitationDecisionRequested` bubble so tests
    can assert the action / content the card emitted.
    """

    def __init__(self, *, message: str, schema: ElicitationSchema) -> None:
        super().__init__()
        self._message = message
        self._schema = schema
        self.bubbles: list[ElicitationDecisionRequested] = []

    def compose(self) -> ComposeResult:
        yield _ElicitationCard(message=self._message, schema=self._schema)

    def on_elicitation_decision_requested(
        self, message: ElicitationDecisionRequested
    ) -> None:
        self.bubbles.append(message)
        message.stop()


def _set_input(input_widget: Input, value: str) -> None:
    input_widget.value = value


# ---------------------------------------------------------------------------
# Mount + render
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_card_renders_message_and_form() -> None:
    """Card mounts with the schema's form widgets and the prompt header.

    The form's per-field type → widget mapping is owned by
    :class:`ElicitationForm` and covered in
    ``tests/input/test_input_panel.py``; here we just verify the card
    surfaces the form and the buttons.
    """
    app = _CardApp(message="What's your secret?", schema=_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(_ElicitationCard)
        form = card.query_one(ElicitationForm)
        # The schema has a string field + a boolean field.
        assert len(form.query(Input)) == 1
        assert len(form.query(Checkbox)) == 1
        # Both buttons present, with the expected ids.
        buttons = {b.id for b in card.query(Button)}
        assert buttons == {"submit-elicitation", "decline-elicitation"}


# ---------------------------------------------------------------------------
# Submit → bubble accept with content
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_submit_with_valid_form_bubbles_accept_with_content() -> None:
    app = _CardApp(message="Hello?", schema=_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(_ElicitationCard)
        form = card.query_one(ElicitationForm)
        _set_input(form.query_one(Input), "world")
        form.query_one(Checkbox).value = True
        await pilot.pause()

        card.query_one("#submit-elicitation", Button).press()
        await pilot.pause()

    assert len(app.bubbles) == 1
    bubble = app.bubbles[0]
    assert bubble.action == "accept"
    assert bubble.content == {"answer": "world", "agree": True}


# ---------------------------------------------------------------------------
# Submit invalid form → no bubble; errors shown
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_submit_invalid_form_does_not_bubble_and_shows_errors() -> None:
    """A required field left blank → no bubble; form shows the error.

    The card stays mounted so the operator can fix the field and
    re-submit. Phase 6a doesn't autoscroll/focus the failed field
    inside the card-test harness (that's covered by ElicitationForm's
    own tests); we just assert the bubble didn't fire.
    """
    app = _CardApp(message="Required check", schema=_schema(required=True))
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(_ElicitationCard)
        # Leave the required ``answer`` field blank, press Submit.
        card.query_one("#submit-elicitation", Button).press()
        await pilot.pause()
        # Inside the pilot context: bubble didn't fire AND the card
        # is still mounted (Phase 6a contract — host unmounts on
        # resolution, not on validation error).
        assert app.bubbles == []
        assert app.query_one(_ElicitationCard) is not None


# ---------------------------------------------------------------------------
# Decline → bubble decline with no content
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_decline_button_bubbles_decline_with_no_content() -> None:
    app = _CardApp(message="Sure?", schema=_schema(required=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(_ElicitationCard)
        card.query_one("#decline-elicitation", Button).press()
        await pilot.pause()

    assert len(app.bubbles) == 1
    bubble = app.bubbles[0]
    assert bubble.action == "decline"
    assert bubble.content is None


# ---------------------------------------------------------------------------
# from_pending convenience constructor
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_from_pending_builds_card_with_correct_message_and_schema() -> None:
    """``_ElicitationCard.from_pending`` copies fields off the PendingElicitation."""
    import asyncio

    from inspect_ai.agent._acp.tui.state import PendingElicitation

    schema = _schema()
    pending = PendingElicitation(
        message="From pending",
        requested_schema=schema,
        event=asyncio.Event(),
    )
    card = _ElicitationCard.from_pending(pending)
    # Internal fields are set; the actual render is covered above.
    assert card._message == "From pending"
    assert card._schema is schema
    # Identity is pinned so the session screen's apply-loop can detect
    # a stale match and remount — see ``_apply_elicitation_card``.
    assert card.pending is pending


# ---------------------------------------------------------------------------
# Empty content map serialization edge case
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_submit_with_only_optional_fields_blank_bubbles_empty_content() -> None:
    """Optional fields left blank → ``content == {}`` (not None).

    Pins the contract the wire handler depends on: ``action=accept``
    always has a content dict (possibly empty), never ``None``.
    """
    schema = ElicitationSchema(
        properties={
            "nickname": ElicitationStringPropertySchema(
                type="string", title="Nickname"
            ),
        },
        required=[],
    )
    app = _CardApp(message="Nothing required", schema=schema)
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.query_one(_ElicitationCard)
        card.query_one("#submit-elicitation", Button).press()
        await pilot.pause()

    assert len(app.bubbles) == 1
    bubble = app.bubbles[0]
    assert bubble.action == "accept"
    assert bubble.content == {}
