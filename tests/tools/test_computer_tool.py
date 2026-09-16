"""Tests for the computer() tool on both sides of the container boundary.

Host side: `execute()` with the container call stubbed. Container side: the
parser and dispatcher from `_resources/tool/` driven directly, minus X11.
"""

import importlib
import logging
import re
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Awaitable, Callable, Iterator, NamedTuple, get_args

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


class Container(NamedTuple):
    parse_arguments: Callable[[list[str]], Namespace]
    computer_tool: ModuleType


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Iterator[Container]:
    """Import the container-side tool as the sandbox runs it, minus X11.

    The modules under `_resources/tool/` use bare imports (`from _args import ...`)
    because the directory is copied into the image as-is, so it goes on sys.path
    for the import and its top-level modules are dropped from `sys.modules` after.
    """
    tool_dir = Path(_common.__file__).parent / "_resources" / "tool"
    monkeypatch.syspath_prepend(str(tool_dir))
    modules_before = set(sys.modules)
    # computer_tool opens /proc/1/fd/1 (PID 1's stdout) at import time
    logger_module = importlib.import_module("_logger")
    monkeypatch.setattr(
        logger_module,
        "setup_logger",
        lambda level=logging.INFO: logging.getLogger("computer_tool"),
    )
    computer_tool = importlib.import_module("computer_tool")

    # execute_action first waits for the X11 session marker file
    async def no_wait(path: str) -> None:
        pass

    monkeypatch.setattr(computer_tool, "wait_for_file", no_wait)
    yield Container(importlib.import_module("_args").parse_arguments, computer_tool)
    for name, module in list(sys.modules.items()):
        if name not in modules_before and str(
            getattr(module, "__file__", "")
        ).startswith(str(tool_dir)):
            del sys.modules[name]


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


@pytest.mark.parametrize("coordinate", [None, [3, 4]])
@pytest.mark.parametrize("action", CLICK_ACTIONS)
async def test_host_click_argv_is_accepted_by_container(
    sent_cmds: list[list[str]],
    container: Container,
    action: str,
    coordinate: list[int] | None,
) -> None:
    """Every click argv the host builds must parse on the container side.

    The host advertising an action the container's parser rejects is fatal for
    the sample (argparse exits non-zero, which `_send_cmd` raises as
    `RuntimeError`), so the two sides are checked against each other here.
    """
    await computer()(action=action, coordinate=coordinate)

    [argv] = sent_cmds
    args = container.parse_arguments(argv)
    assert args.action == action
    assert args.coordinate == coordinate


@pytest.mark.parametrize("text", [None, "shift"])
@pytest.mark.parametrize("coordinate", [None, [3, 4]])
@pytest.mark.parametrize("action", CLICK_ACTIONS)
async def test_container_dispatches_click_to_x11_client(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    coordinate: list[int] | None,
    text: str | None,
) -> None:
    # The fake below answers any name, so pin the real client's surface first.
    assert callable(getattr(container.computer_tool.X11Client, action))

    calls: list[tuple[str, list[int] | None, str | None]] = []

    class FakeX11Client:
        # Records whichever method the dispatcher calls, so a case wired to the
        # wrong X11 method shows up as a mismatched name.
        def __getattr__(self, name: str) -> Callable[..., Awaitable[str]]:
            async def record(coord: list[int] | None, text: str | None) -> str:
                calls.append((name, coord, text))
                return "ok"

            return record

    monkeypatch.setattr(container.computer_tool, "X11Client", FakeX11Client)

    argv = [action]
    if coordinate:
        argv += ["--coordinate", "3", "4"]
    if text:
        argv += ["--text", text]
    await container.computer_tool.execute_action(container.parse_arguments(argv))
    assert calls == [(action, coordinate, text)]
