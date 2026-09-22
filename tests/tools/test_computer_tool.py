"""Unit tests for the computer() tool definition (no sandbox required)."""

import pytest

from inspect_ai.tool import computer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._computer import _common


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


@pytest.mark.parametrize("repeat", [0, -1, 101, 100000])
async def test_computer_key_rejects_out_of_range_repeat(
    monkeypatch: pytest.MonkeyPatch, repeat: int
) -> None:
    from inspect_ai.tool._tool import ToolParsingError

    presses: list[str] = []

    async def fake_press_key(key: str, timeout: int | None = None) -> str:
        presses.append(key)
        return "OK"

    monkeypatch.setattr(_common, "press_key", fake_press_key)

    with pytest.raises(ToolParsingError, match="repeat must be between 1 and 100"):
        await computer()(action="key", text="Return", repeat=repeat)
    assert presses == []


def _computer_call(call_id: str, **arguments: object):
    from inspect_ai.tool._tool_call import ToolCall

    return ToolCall(id=call_id, function="computer", arguments=arguments)


@pytest.mark.parametrize(
    "repeat,expected_presses",
    [(3, 3), (3.0, 3), ("3", 3), (None, 1)],
)
async def test_nested_actions_repeat_accepts_integral_values(
    monkeypatch: pytest.MonkeyPatch, repeat: object, expected_presses: int
) -> None:
    """`actions` entries bypass top-level conversion; integral values still work."""
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool

    init_transcript(Transcript())
    presses: list[str] = []

    async def fake_press_key(key: str, timeout: int | None = None) -> str:
        presses.append(key)
        return "OK"

    monkeypatch.setattr(_common, "press_key", fake_press_key)

    entry: dict[str, object] = {"action": "key", "text": "Return"}
    if repeat is not None:
        entry["repeat"] = repeat
    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content="", tool_calls=[_computer_call("c0", actions=[entry])]
            )
        ],
        [ToolDef(computer())],
    )
    tool_msg = next(m for m in messages if isinstance(m, ChatMessageTool))
    assert tool_msg.error is None
    assert presses == ["Return"] * expected_presses


@pytest.mark.parametrize("repeat", [1.5, "three", True, 0, -2, 101])
async def test_nested_actions_repeat_rejects_invalid_values_before_pressing(
    monkeypatch: pytest.MonkeyPatch, repeat: object
) -> None:
    """A malformed nested `repeat` is a parsing error with no side effects."""
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool

    init_transcript(Transcript())
    presses: list[str] = []

    async def fake_press_key(key: str, timeout: int | None = None) -> str:
        presses.append(key)
        return "OK"

    monkeypatch.setattr(_common, "press_key", fake_press_key)

    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content="",
                tool_calls=[
                    _computer_call(
                        "c0",
                        actions=[{"action": "key", "text": "Return", "repeat": repeat}],
                    )
                ],
            )
        ],
        [ToolDef(computer())],
    )
    tool_msg = next(m for m in messages if isinstance(m, ChatMessageTool))
    assert tool_msg.error is not None and tool_msg.error.type == "parsing"
    assert "repeat must be" in tool_msg.error.message
    assert presses == []
