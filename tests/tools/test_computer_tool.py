"""Host-side tests for the computer() tool, with the container call stubbed."""

import re
from typing import get_args

import pytest

from inspect_ai.tool import ToolResult, computer
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tools._computer import _common
from inspect_ai.tool._tools._computer._computer import Action

ACTIONS: list[str] = list(get_args(Action))

CLICK_ACTIONS: list[str] = [
    "left_click",
    "right_click",
    "middle_click",
    "back_click",
    "forward_click",
    "double_click",
    "triple_click",
]

# Satisfies every required parameter of each action *other than* `coordinate`,
# so a refusal below can only be about `coordinate`.
OTHER_ARGS: dict[str, dict[str, object]] = {
    "key": {"text": "a"},
    "hold_key": {"text": "a", "duration": 1},
    "type": {"text": "a"},
    "left_click_drag": {"start_coordinate": [1, 1]},
    "scroll": {"scroll_amount": 1, "scroll_direction": "up"},
    "wait": {"duration": 1},
    "zoom": {"region": [0, 0, 1, 1]},
    "navigate": {"text": "https://example.com"},
}


@pytest.fixture
def sent_cmds(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stub the container call and collect the argv of every command sent."""
    cmds: list[list[str]] = []

    async def fake_send_cmd(cmd: list[str], timeout: int | None = None) -> ToolResult:
        cmds.append(cmd)
        return "OK"

    monkeypatch.setattr(_common, "_send_cmd", fake_send_cmd)
    return cmds


async def test_coordinate_description_matches_dispatch(
    sent_cmds: list[list[str]],
) -> None:
    """The `coordinate` description names exactly the actions that use it.

    The description is the only place the model is told which actions need a
    coordinate (every parameter is optional in the schema), so this derives
    the truth from the dispatch itself rather than restating it.
    """
    execute = computer()

    required: set[str] = set()
    for action in ACTIONS:
        try:
            await execute(action=action, **OTHER_ARGS.get(action, {}))
        except ToolParsingError as ex:
            if str(ex) == "coordinate must be provided":
                required.add(action)

    optional: set[str] = set()
    for action in ACTIONS:
        if action in required:
            continue
        sent_cmds.clear()
        await execute(action=action, coordinate=[3, 4], **OTHER_ARGS.get(action, {}))
        if any("--coordinate" in cmd for cmd in sent_cmds):
            optional.add(action)

    assert required == {"mouse_move", "left_click_drag"}, (
        f"actions that refuse to run without a coordinate: {sorted(required)}"
    )
    assert optional == set(CLICK_ACTIONS) | {"scroll", "type"}, (
        f"actions that send a coordinate when given one: {sorted(optional)}"
    )

    description = (
        parse_tool_info(execute).parameters.properties["coordinate"].description
    )
    assert description is not None
    required_text, sep, optional_text = description.partition("Optional for")
    assert sep, (
        "description should have a 'Required by ...' and an 'Optional for ...' part"
    )
    assert set(re.findall(r"`action=(\w+)`", required_text)) == required, (
        f"'Required by' should name each of {sorted(required)} as `action=...`"
    )
    assert set(re.findall(r"`action=(\w+)`", optional_text)) == optional, (
        f"'Optional for' should name each of {sorted(optional)} as `action=...`"
    )


@pytest.mark.parametrize("action", CLICK_ACTIONS)
async def test_click_without_coordinate_clicks_in_place(
    sent_cmds: list[list[str]], action: str
) -> None:
    execute = computer()

    await execute(action=action)
    assert sent_cmds == [[action]]

    sent_cmds.clear()
    await execute(action=action, coordinate=[3, 4])
    assert sent_cmds == [[action, "--coordinate", "3", "4"]]


@pytest.mark.parametrize("coordinate", [[], [5], [1, 2, 3]])
@pytest.mark.parametrize("action", ["left_click", "mouse_move", "scroll", "type"])
async def test_malformed_coordinate_is_reported_to_model(
    sent_cmds: list[list[str]], action: str, coordinate: list[int]
) -> None:
    execute = computer()

    with pytest.raises(ToolParsingError, match=r"^coordinate must be \[x, y\]$"):
        await execute(
            action=action, coordinate=coordinate, **OTHER_ARGS.get(action, {})
        )
    assert sent_cmds == []


async def test_malformed_start_coordinate_is_reported_to_model(
    sent_cmds: list[list[str]],
) -> None:
    execute = computer()

    with pytest.raises(ToolParsingError, match=r"^start_coordinate must be \[x, y\]$"):
        await execute(action="left_click_drag", start_coordinate=[1], coordinate=[3, 4])
    assert sent_cmds == []
