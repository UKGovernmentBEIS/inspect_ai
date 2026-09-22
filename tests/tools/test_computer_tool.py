"""Unit tests for the computer() tool definition (no sandbox required)."""

import pytest

from inspect_ai.tool import computer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._computer import _common


def test_computer_tool_is_serial_and_halts_on_error() -> None:
    """GUI actions in one turn are order-dependent: never parallel, halt on error."""
    tdef = ToolDef(computer())
    assert tdef.parallel is False
    assert tdef.halt_on_error is True


@pytest.mark.parametrize("repeat,expected", [(None, 1), (1, 1), (3, 3)])
async def test_computer_key_honors_repeat(
    monkeypatch: pytest.MonkeyPatch, repeat: int | None, expected: int
) -> None:
    presses: list[str] = []

    async def fake_press_key(key: str, timeout: int | None = None) -> str:
        presses.append(key)
        return "OK"

    monkeypatch.setattr(_common, "press_key", fake_press_key)

    tool = computer()
    kwargs = {"repeat": repeat} if repeat is not None else {}
    result = await tool(action="key", text="Return", **kwargs)
    assert result == "OK"
    assert presses == ["Return"] * expected
