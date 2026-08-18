"""Tests for the :class:`InlineRequestCard` base widget.

The base supplies the bordered Vertical, the bold header, the
actions row, the identity slot, and the focus-first behavior;
subclasses (elicitation / approval / cancel) fill in
``header_text`` + ``compose_body`` + ``compose_actions``. These
tests use a minimal concrete subclass so we can exercise the
contract without leaning on the request-kind-specific widgets.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Button, Input

from inspect_ai.agent._acp.tui.widgets.inline_request_card import (
    InlineRequestCard,
)


class _StubCard(InlineRequestCard):
    """Minimal subclass for base-class contract tests.

    Header is a fixed string; body yields a single :class:`Input`
    (so we have a focusable body widget to verify focus-first);
    actions yield two compact :class:`Button`s.
    """

    def __init__(self, header: str = "Pick one") -> None:
        super().__init__()
        self._header = header

    @property
    def header_text(self) -> str:
        return self._header

    def compose_body(self) -> ComposeResult:
        yield Input(id="body-input", placeholder="type something")

    def compose_actions(self) -> ComposeResult:
        yield Button("OK", id="ok", compact=True)
        yield Button("Cancel", id="cancel", compact=True)


class _Host(App[None]):
    def __init__(self, card: InlineRequestCard) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        yield self._card


@skip_if_trio
@pytest.mark.anyio
async def test_compose_yields_header_body_and_actions() -> None:
    """The base lays out header → body → actions in a single Vertical."""
    from textual.widgets import Static

    card = _StubCard("My question")
    async with _Host(card).run_test() as pilot:
        # Header text is wrapped in a Static with the request-header class.
        header = pilot.app.query_one(".request-header", Static)
        assert "My question" in str(header.render())
        # The body Input is mounted.
        body = pilot.app.query_one("#body-input", Input)
        assert body is not None
        # The actions row contains both buttons.
        actions = pilot.app.query_one("#request-actions")
        buttons = list(actions.query(Button))
        assert [b.id for b in buttons] == ["ok", "cancel"]


@skip_if_trio
@pytest.mark.anyio
async def test_on_mount_focuses_first_focusable_descendant() -> None:
    """``on_mount`` lands focus on the body field, not on an action button.

    Focus on the actions row would let an early Space activate a
    button before the operator has read the card.
    """
    card = _StubCard()
    async with _Host(card).run_test() as pilot:
        focused = pilot.app.focused
        assert focused is not None
        # The Input (first focusable in compose order) should win.
        assert focused.id == "body-input"


@skip_if_trio
@pytest.mark.anyio
async def test_request_identity_slot_defaults_to_none() -> None:
    """``.request`` is None by default; subclasses set it via ``from_*``."""
    card = _StubCard()
    assert card.request is None
    sentinel: Any = object()
    card.request = sentinel
    assert card.request is sentinel


def test_compose_body_unimplemented_on_base() -> None:
    """The base raises if a subclass forgets to override ``compose_body``."""

    class _Bare(InlineRequestCard):
        @property
        def header_text(self) -> str:
            return "x"

        # compose_body / compose_actions inherited — both raise.

    with pytest.raises(NotImplementedError):
        list(_Bare().compose_body())


def test_compose_actions_unimplemented_on_base() -> None:
    """The base raises if a subclass forgets to override ``compose_actions``."""

    class _Bare(InlineRequestCard):
        @property
        def header_text(self) -> str:
            return "x"

        def compose_body(self) -> ComposeResult:
            return
            yield  # pragma: no cover

    with pytest.raises(NotImplementedError):
        list(_Bare().compose_actions())
