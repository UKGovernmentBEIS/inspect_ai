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


# ---------------------------------------------------------------------------
# Mount-time focus + Enter dispatch (parity with approval / cancel cards)
# ---------------------------------------------------------------------------


def _single_string_schema() -> ElicitationSchema:
    """Single required string property — minimal viable single-field form.

    Used by the Enter-only-field / focus-first tests below; mirrors
    the demo schema in ``examples/inline_cards/question.py``.
    """
    return ElicitationSchema(
        properties={
            "answer": ElicitationStringPropertySchema(type="string", title="Answer"),
        },
        required=["answer"],
    )


def _two_string_schema() -> ElicitationSchema:
    """Two required string properties — minimal viable multi-field form.

    Used to exercise the advance-on-Enter path; mirrors the
    two-property schema in ``examples/inline_cards/question.py``.
    """
    return ElicitationSchema(
        properties={
            "environment": ElicitationStringPropertySchema(
                type="string", title="Environment"
            ),
            "expiry": ElicitationStringPropertySchema(type="string", title="Expiry"),
        },
        required=["environment", "expiry"],
    )


@skip_if_trio
@pytest.mark.anyio
async def test_mount_focuses_first_form_input() -> None:
    """On mount, focus lands on the first Input — parity with approval / cancel.

    Approval / cancel cards inherit the base
    :meth:`InlineRequestCard.on_mount` first-focusable walk, which
    lands on a Button. Elicitation overrides on_mount to instead
    route through :meth:`ElicitationForm.focus_first` so the
    cursor lands on the first form input rather than the header
    Static. The override defers via ``call_after_refresh`` because
    layout hasn't run by the time the parent's on_mount fires —
    without the defer the focus call silently no-ops against the
    not-yet-laid-out subtree.
    """
    app = _CardApp(message="What's your name?", schema=_single_string_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        # call_after_refresh fires AFTER the next refresh, which
        # pilot.pause() advances; a second pause covers any extra
        # message-pump tick between the focus call and pilot
        # observing it.
        await pilot.pause()
        inputs = list(app.query(Input))
        assert len(inputs) == 1
        assert app.focused is inputs[0]


@skip_if_trio
@pytest.mark.anyio
async def test_enter_on_only_field_submits() -> None:
    """Single-field form: Enter on the Input → accept bubble with the typed value.

    The card listens for :class:`Input.Submitted` (which Textual's
    Input emits on Enter, stopping the original keypress). With no
    later empty-required field, :meth:`focus_next_empty_required`
    returns False and the card falls through to ``_submit``.
    """
    app = _CardApp(message="What's your name?", schema=_single_string_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        only_input = app.query_one(Input)
        only_input.value = "alice"
        # ``Input.action_submit`` is async (posts ``Input.Submitted``);
        # going through ``pilot.press("enter")`` exercises the full
        # key path — the Input's own Enter binding fires
        # ``action_submit``, which awaits and emits the bubble.
        # Relies on mount-time focus landing on this Input
        # (pinned by ``test_mount_focuses_first_form_input``).
        await pilot.press("enter")
        await pilot.pause()

    assert len(app.bubbles) == 1
    assert app.bubbles[0].action == "accept"
    assert app.bubbles[0].content == {"answer": "alice"}


@skip_if_trio
@pytest.mark.anyio
async def test_enter_on_first_field_advances_when_second_empty() -> None:
    """Multi-field form: Enter on the first field advances focus, no submit.

    Pins the "advance, then submit" semantic from the plan: with a
    later required field still empty,
    :meth:`focus_next_empty_required` returns True and the card
    does NOT call _submit. Focus moves to the next FieldRow's
    Input.

    Assertions stay inside the ``async with`` because
    ``app.focused`` reaches into the screen stack — which is
    popped on context exit.
    """
    app = _CardApp(message="Two fields", schema=_two_string_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        inputs = list(app.query(Input))
        assert len(inputs) == 2
        first, second = inputs
        first.value = "staging"
        await pilot.press("enter")
        await pilot.pause()
        # No submit bubble fired — the form is still being filled.
        assert app.bubbles == []
        # Focus advanced to the second Input.
        assert app.focused is second


@skip_if_trio
@pytest.mark.anyio
async def test_enter_on_last_field_submits_when_all_filled() -> None:
    """Multi-field form: Enter on the last empty-required field → submit.

    Companion to the advance test above. Once every required
    field is non-empty, ``focus_next_empty_required`` exhausts
    its walk and returns False, so the card falls through to
    ``_submit`` and the bubble carries the full content.
    """
    app = _CardApp(message="Two fields", schema=_two_string_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        inputs = list(app.query(Input))
        first, second = inputs
        first.value = "staging"
        second.value = "tomorrow"
        # Move focus to the second input first, then press Enter
        # so the bubble lands as if the operator finished typing
        # there.
        second.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert len(app.bubbles) == 1
    assert app.bubbles[0].action == "accept"
    assert app.bubbles[0].content == {
        "environment": "staging",
        "expiry": "tomorrow",
    }


@skip_if_trio
@pytest.mark.anyio
async def test_enter_with_all_required_empty_submits_and_surfaces_error() -> None:
    """Required field empty, no later empty-required field → submit fires and errors.

    Single-field form, Enter on the empty Input: the card's
    advance-or-submit dispatch finds no later empty-required
    field (there are no later fields at all), so it falls through
    to ``_submit``. ``_submit`` calls ``form.collect``, which
    returns an error, which the form marks on the row via the
    ``has-error`` CSS class (the inline error Static is
    ``display: none`` until that class is present — see the
    ElicitationForm DEFAULT_CSS).
    """
    from inspect_ai._util.textual.form import FieldRow

    app = _CardApp(message="Required field", schema=_single_string_schema())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # Leave the value blank; press Enter on the focused Input.
        await pilot.press("enter")
        await pilot.pause()
        # No accept bubble — submit short-circuited on validation.
        assert app.bubbles == []
        # The form marked its required-and-empty row as in error.
        rows = list(app.query(FieldRow))
        assert rows, "FieldRow not mounted"
        assert any("has-error" in r.classes for r in rows), (
            f"expected at least one FieldRow with class has-error after "
            f"submit-on-empty, got classes={[list(r.classes) for r in rows]}"
        )
