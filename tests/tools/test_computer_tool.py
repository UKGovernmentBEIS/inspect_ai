"""Tests for the computer() tool on both sides of the container boundary.

Host side: `execute()` with the container call stubbed. Container side: the
parser and dispatcher from `_resources/tool/` driven directly, minus X11.
"""

import importlib
import json
import logging
import math
import re
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Awaitable, Callable, Iterator, NamedTuple, get_args

import pytest

from inspect_ai.tool import ToolError, ToolResult, computer
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tools._computer import _common
from inspect_ai.tool._tools._computer._computer import Action
from inspect_ai.util import ExecResult

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
    # computer_tool opens /proc/1/fd/1 (PID 1's stdout) at import time. Keep its
    # logger off the root handlers too: once an earlier test has run `eval()`,
    # root logs to stdout, which would end up in the JSON the tests parse.
    tool_logger = logging.getLogger("computer_tool")
    monkeypatch.setattr(tool_logger, "propagate", False)
    null_handler = logging.NullHandler()
    tool_logger.addHandler(null_handler)
    logger_module = importlib.import_module("_logger")
    monkeypatch.setattr(
        logger_module, "setup_logger", lambda level=logging.INFO: tool_logger
    )
    computer_tool = importlib.import_module("computer_tool")

    # execute_action first waits for the X11 session marker file
    async def no_wait(path: str) -> None:
        pass

    monkeypatch.setattr(computer_tool, "wait_for_file", no_wait)
    yield Container(importlib.import_module("_args").parse_arguments, computer_tool)
    tool_logger.removeHandler(null_handler)
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


class X11(NamedTuple):
    client: Any
    errors: type[Exception]
    shell_cmds: list[str]


@pytest.fixture
def x11(container: Container, monkeypatch: pytest.MonkeyPatch) -> X11:
    """A 1920x1080 container-side X11Client (advertised to the model as 1366x768)."""
    monkeypatch.setenv("WIDTH", "1920")
    monkeypatch.setenv("HEIGHT", "1080")
    x11_client = importlib.import_module("_x11_client")
    client = x11_client.X11Client()
    shell_cmds: list[str] = []

    async def fake_shell(command: str, take_screenshot: bool = True) -> str:
        shell_cmds.append(command)
        return "ok"

    monkeypatch.setattr(client, "_shell", fake_shell)
    return X11(client, x11_client.X11ClientError, shell_cmds)


@pytest.mark.parametrize(
    "api,native",
    [
        ((0, 0), (0, 0)),
        ((1000, 500), (1406, 703)),
        ((1365, 767), (1919, 1079)),
    ],
)
def test_x11_scale_api_coordinate_in_bounds(
    x11: X11, api: tuple[int, int], native: tuple[int, int]
) -> None:
    assert x11.client._scale_coordinates("api_to_native", *api) == native


@pytest.mark.parametrize(
    "api",
    [
        (1800, 100),  # past the API width, but inside the native width
        (100, 900),
        (1366, 768),  # one past the last column and row
        (1366, 100),
        (100, 768),
        (1920, 1080),
        (1921, 100),
        (-5, 100),
        (100, -5),
    ],
)
def test_x11_scale_rejects_out_of_bounds_api_coordinate(
    x11: X11, api: tuple[int, int]
) -> None:
    with pytest.raises(x11.errors, match="out of bounds"):
        x11.client._scale_coordinates("api_to_native", *api)


def test_x11_scale_region_end_allows_screen_edge(x11: X11) -> None:
    scale = x11.client._scale_coordinates
    assert scale("api_to_native", 1366, 768, region_end=True) == (1920, 1080)
    with pytest.raises(x11.errors):
        scale("api_to_native", 1367, 768, region_end=True)
    with pytest.raises(x11.errors):
        scale("api_to_native", -1, 0, region_end=True)


def test_x11_scale_native_to_api_is_not_bounds_checked(x11: X11) -> None:
    assert x11.client._scale_coordinates("native_to_api", 1920, 1080) == (1366, 768)


def test_x11_scale_checks_native_bounds_when_scaling_disabled(x11: X11) -> None:
    x11.client._scaling_enabled = False
    assert x11.client._scale_coordinates("api_to_native", 1919, 1079) == (1919, 1079)
    for bad in [(1920, 100), (100, 1080), (-1, 100)]:
        with pytest.raises(x11.errors):
            x11.client._scale_coordinates("api_to_native", *bad)


def test_x11_scale_checks_native_bounds_without_scaling_target(
    x11: X11, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1:1 aspect ratio matches no entry in MAX_SCALING_TARGETS
    monkeypatch.setattr(x11.client, "width", 1024)
    monkeypatch.setattr(x11.client, "height", 1024)
    assert x11.client._scale_coordinates("api_to_native", 1023, 1023) == (1023, 1023)
    with pytest.raises(x11.errors):
        x11.client._scale_coordinates("api_to_native", 1024, 100)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.mouse_move((1800, 100)),
        lambda c: c.left_click((1800, 100), None),
        lambda c: c.scroll("down", 1, (1800, 100), None),
        lambda c: c.left_click_drag((10, 10), (1800, 100)),
        lambda c: c.left_click_drag((1800, 100), (10, 10)),
        lambda c: c.zoom([0, 0, 1800, 100]),
        lambda c: c.zoom([1366, 0, 1367, 100]),
    ],
    ids=[
        "mouse_move",
        "left_click",
        "scroll",
        "drag_end",
        "drag_start",
        "zoom_far_corner",
        "zoom_near_corner",
    ],
)
async def test_x11_actions_reject_out_of_bounds_coordinate(
    x11: X11, call: Callable[[Any], Awaitable[object]]
) -> None:
    with pytest.raises(x11.errors, match="out of bounds"):
        await call(x11.client)
    assert not any("mousedown" in c or "click" in c for c in x11.shell_cmds)


async def test_x11_actions_send_scaled_native_coordinates(x11: X11) -> None:
    await x11.client.mouse_move((1000, 500))
    await x11.client.left_click_drag((1000, 500), (1365, 767))
    assert any("mousemove --sync 1406 703" in c for c in x11.shell_cmds)
    assert any("mousemove --sync 1919 1079 mouseup 1" in c for c in x11.shell_cmds)


async def test_x11_zoom_accepts_full_screen_region(
    x11: X11, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[int, int, int, int]] = []

    async def fake_screenshot(
        zoom_region: tuple[int, int, int, int] | None = None,
    ) -> str:
        assert zoom_region is not None
        seen.append(zoom_region)
        return "ok"

    monkeypatch.setattr(x11.client, "_screenshot", fake_screenshot)
    await x11.client.zoom([0, 0, 1366, 768])
    assert seen == [(0, 0, 1920, 1080)]
    with pytest.raises(x11.errors):
        await x11.client.zoom([0, 0, 1367, 768])


@pytest.mark.parametrize(
    "native,api",
    [
        ((1920, 1080), (1366, 768)),  # FWXGA
        ((3840, 2160), (1366, 768)),  # FWXGA
        ((2560, 1600), (1280, 800)),  # WXGA
        ((1920, 1440), (1024, 768)),  # XGA
        ((1280, 800), (1280, 800)),  # at the target size: no scaling
        ((1024, 768), (1024, 768)),  # at the target size: no scaling
    ],
)
def test_x11_scale_bounds_follow_advertised_size(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    native: tuple[int, int],
    api: tuple[int, int],
) -> None:
    monkeypatch.setenv("WIDTH", str(native[0]))
    monkeypatch.setenv("HEIGHT", str(native[1]))
    x11_client = importlib.import_module("_x11_client")
    client = x11_client.X11Client()
    scale = client._scale_coordinates
    assert (
        client.options["display_width_px"],
        client.options["display_height_px"],
    ) == api

    # last pixel maps within one scale step of the last native pixel
    x, y = scale("api_to_native", api[0] - 1, api[1] - 1)
    assert native[0] - math.ceil(native[0] / api[0]) <= x <= native[0] - 1
    assert native[1] - math.ceil(native[1] / api[1]) <= y <= native[1] - 1

    for bad in [
        (api[0], 0),
        (0, api[1]),
        (-1, 0),
        (0, -1),
        (native[0], 0),
        (0, native[1]),
    ]:
        with pytest.raises(x11_client.X11ClientError, match="out of bounds"):
            scale("api_to_native", *bad)

    # a region may end on the advertised width/height, but not beyond
    assert scale("api_to_native", *api, region_end=True) == native
    with pytest.raises(x11_client.X11ClientError):
        scale("api_to_native", api[0] + 1, api[1], region_end=True)


def _run_container_main(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> dict[str, Any]:
    """Run `computer_tool.main()` as the sandbox does and return its JSON stdout."""
    monkeypatch.setattr(sys, "argv", ["computer_tool.py", *argv])
    container.computer_tool.main()
    return json.loads(capsys.readouterr().out)


def _patch_container_x11(
    container: Container, monkeypatch: pytest.MonkeyPatch, x11: X11
) -> None:
    result_module = importlib.import_module("_tool_result")

    async def fake_shell(command: str, take_screenshot: bool = True) -> object:
        x11.shell_cmds.append(command)
        return result_module.ToolResult(output="ok")

    monkeypatch.setattr(x11.client, "_shell", fake_shell)
    monkeypatch.setattr(container.computer_tool, "X11Client", lambda: x11.client)


def test_container_reports_out_of_bounds_coordinate_as_error(
    container: Container,
    x11: X11,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_container_x11(container, monkeypatch, x11)
    out = _run_container_main(
        container, monkeypatch, capsys, ["left_click", "--coordinate", "1800", "100"]
    )
    assert "out of bounds" in out["error"]
    assert out["output"] is None and out["base64_image"] is None
    assert not any("mousedown" in c or "click" in c for c in x11.shell_cmds)


def test_container_reports_invalid_zoom_region_as_error(
    container: Container,
    x11: X11,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_container_x11(container, monkeypatch, x11)
    out = _run_container_main(
        container, monkeypatch, capsys, ["zoom", "--region", "0", "0", "0", "0"]
    )
    assert out["error"] == "Invalid region"


def test_container_valid_call_succeeds_after_out_of_bounds_call(
    container: Container,
    x11: X11,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_container_x11(container, monkeypatch, x11)
    bad = _run_container_main(
        container, monkeypatch, capsys, ["left_click", "--coordinate", "1800", "100"]
    )
    assert bad["error"]
    good = _run_container_main(
        container, monkeypatch, capsys, ["left_click", "--coordinate", "1000", "500"]
    )
    assert good["error"] is None and good["output"] == "ok"
    assert any("mousemove --sync 1406 703" in c for c in x11.shell_cmds)


def test_container_other_x11_errors_still_fail_the_command(
    container: Container,
    x11: X11,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def broken_screenshot(*args: object, **kwargs: object) -> object:
        raise importlib.import_module("_x11_client").X11ClientError(
            "Failed to take screenshot"
        )

    monkeypatch.setattr(x11.client, "screenshot", broken_screenshot, raising=False)
    monkeypatch.setattr(container.computer_tool, "X11Client", lambda: x11.client)
    monkeypatch.setattr(sys, "argv", ["computer_tool.py", "screenshot"])
    with pytest.raises(SystemExit) as exit_info:
        container.computer_tool.main()
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Failed to take screenshot" in captured.err


async def test_host_raises_tool_error_for_container_coordinate_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The container's error JSON becomes a `ToolError`, not a `RuntimeError`."""
    stdout = json.dumps(
        {
            "output": None,
            "error": "Coordinates 1800, 100 are out of bounds for a 1366x768 screen",
            "base64_image": None,
        }
    )

    class FakeSandbox:
        async def exec(
            self, cmd: list[str], timeout: int | None = None
        ) -> ExecResult[str]:
            return ExecResult(success=True, returncode=0, stdout=stdout, stderr="")

    async def fake_computer_sandbox() -> object:
        return FakeSandbox()

    sample = SimpleNamespace(sample=SimpleNamespace(id=1))
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)
    monkeypatch.setattr(_common, "computer_sandbox", fake_computer_sandbox)

    with pytest.raises(ToolError, match="out of bounds"):
        await _common._send_cmd(["left_click", "--coordinate", "1800", "100"])
