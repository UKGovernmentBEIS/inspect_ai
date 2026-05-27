import json
from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, Field

from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import ContentImage
from inspect_ai.tool import ToolError, ToolResult
from inspect_ai.util._sandbox.context import sandbox_with
from inspect_ai.util._sandbox.environment import SandboxEnvironment


class ToolExecResult(BaseModel):
    output: str | None = Field(default=None)
    error: str | None = Field(default=None)
    base64_image: str | None = Field(default=None)


async def cursor_position(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["cursor_position"], timeout=timeout)


async def screenshot(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["screenshot"], timeout=timeout)


async def wait(duration: int, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["wait", "--duration", f"{duration}"], timeout=timeout)


async def mouse_move(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["mouse_move", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def left_mouse_down(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["left_mouse_down"], timeout=timeout)


async def left_mouse_up(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["left_mouse_up"], timeout=timeout)


async def left_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["left_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def left_click_drag(
    start_coordinate: list[int], coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    return await _send_cmd(
        [
            "left_click_drag",
            "--start_coordinate",
            f"{start_coordinate[0]}",
            f"{start_coordinate[1]}",
            "--coordinate",
            f"{coordinate[0]}",
            f"{coordinate[1]}",
        ],
        timeout=timeout,
    )


async def right_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["right_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def middle_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["middle_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def back_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["back_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def forward_click(
    coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    return await _send_cmd(
        ["forward_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def double_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["double_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def triple_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["triple_click", "--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"],
        timeout=timeout,
    )


async def scroll(
    scroll_amount: int,
    scroll_direction: Literal["up", "down", "left", "right"],
    coordinate: list[int] | None,
    timeout: int | None = None,
) -> ToolResult:
    return await _send_cmd(
        [
            "scroll",
            "--scroll_amount",
            f"{scroll_amount}",
            "--scroll_direction",
            f"{scroll_direction}",
        ]
        + (
            ["--coordinate", f"{coordinate[0]}", f"{coordinate[1]}"]
            if coordinate
            else []
        ),
        timeout=timeout,
    )


async def press_key(key: str, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["key", "--text", _normalize_key_text(key)], timeout=timeout)


async def hold_key(key: str, duration: int, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["hold_key", "--text", _normalize_key_text(key), "--duration", f"{duration}"],
        timeout=timeout,
    )


async def type(text: str, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["type", f"--text={text}"], timeout=timeout)


async def zoom(region: list[int], timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        [
            "zoom",
            "--region",
            str(region[0]),
            str(region[1]),
            str(region[2]),
            str(region[3]),
        ],
        timeout=timeout,
    )


async def open_web_browser(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["open_web_browser"], timeout=timeout)


async def navigate(text: str, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["navigate", "--text", text], timeout=timeout)


async def _send_cmd(cmdTail: list[str], timeout: int | None = None) -> ToolResult:
    from inspect_ai.log._samples import sample_active

    sample = sample_active()
    assert sample
    sample_id = sample.sample.id
    assert sample_id

    cmd = ["python3", "/opt/inspect/tool/computer_tool.py"] + cmdTail

    raw_exec_result = await (await computer_sandbox()).exec(cmd, timeout=timeout)

    if not raw_exec_result.success:
        raise RuntimeError(
            f"Failure executing command: ${cmd} {raw_exec_result.stderr}"
        )

    result = ToolExecResult(**json.loads(raw_exec_result.stdout))

    if result.error:
        raise ToolError(result.error)

    image = (
        ContentImage(image=f"data:image/png;base64,{result.base64_image}")
        if result.base64_image
        else None
    )
    text = result.output if result.output and len(result.output) > 0 else None

    if text is not None and image is not None:
        return [ContentText(text=text), image]

    if text is not None:
        return text

    if image is not None:
        return [image]

    return "OK"


# Translate model key names to xdotool keysyms.
#
# xdotool's XStringToKeysym is case-sensitive (e.g. "Return" not "return").
# Anthropic's reference impl (anthropics/anthropic-quickstarts) passes key text
# straight to xdotool with no normalization, implying Claude is trained to emit
# xdotool keysyms — but this isn't formally documented.  OpenAI uses its own key
# vocabulary (UPPERCASE), mapped upstream in _openai_computer_use.py.  Non-native
# models see the tool docstring which lists xdotool examples.
#
# This table handles case normalization of keysyms plus common alternate names
# (e.g. "Enter" -> "Return").  Unrecognized keys pass through to xdotool which
# will error back to the model.  Modifiers (ctrl/alt/shift/super/meta) are
# already case-insensitive in xdotool so they're excluded.  Single characters
# are handled separately in _normalize_key_combo.
_KEY_ALIASES: dict[str, str] = {}
for _name in [
    "Return",
    "Escape",
    "BackSpace",
    "Tab",
    "Delete",
    "Insert",
    "Home",
    "End",
    "Prior",
    "Next",
    "Left",
    "Up",
    "Right",
    "Down",
    "Pause",
    "space",
    "Scroll_Lock",
    "Num_Lock",
    "Caps_Lock",
    "Shift_L",
    "Shift_R",
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "Super_L",
    "Super_R",
    "Meta_L",
    "Meta_R",
    *[f"F{i}" for i in range(1, 13)],
    *[
        f"KP_{s}"
        for s in [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "Enter",
            "Add",
            "Subtract",
            "Multiply",
            "Divide",
            "Decimal",
            "Equal",
            "Home",
            "Up",
            "Prior",
            "Left",
            "Begin",
            "Right",
            "End",
            "Down",
            "Next",
            "Insert",
            "Delete",
        ]
    ],
]:
    _KEY_ALIASES[_name.lower()] = _name

# Common alternate names that models use but aren't xdotool keysyms.
_KEY_ALIASES.update(
    {
        "enter": "Return",
        "esc": "Escape",
        "pageup": "Prior",
        "pagedown": "Next",
        "arrowleft": "Left",
        "arrowup": "Up",
        "arrowright": "Right",
        "arrowdown": "Down",
        # xdotool doesn't recognize "PRINTSCREEN" or "PRTSCR" — it needs the keysym name "Print".
        "printscreen": "Print",
        "prtscr": "Print",
        # Modifier abbreviations — map to xdotool's built-in aliases
        "ctl": "ctrl",
        "control": "ctrl",
        "cmd": "super",
        "command": "super",
        "win": "super",
        "windows": "super",
        "opt": "alt",
        "option": "alt",
        # xdotool doesn't recognize "," — it needs the keysym name "comma".
        ",": "comma",
    }
)


def _normalize_key_combo(combo: str) -> str:
    """Normalize a single key combo (e.g. "ctrl+ENTER") for xdotool."""
    parts = combo.split("+")
    is_combo = len(parts) > 1
    normalized = []
    for part in parts:
        if len(part) == 1 and part.isalpha():
            normalized.append(part.lower() if is_combo else part)
        else:
            normalized.append(_KEY_ALIASES.get(part.lower(), part))
    return "+".join(normalized)


def _normalize_key_text(text: str) -> str:
    """Normalize key text which may contain space-separated combos."""
    return " ".join(_normalize_key_combo(part) for part in text.split())


async def computer_sandbox() -> SandboxEnvironment:
    sb = await sandbox_with("/opt/inspect/tool/computer_tool.py")
    if sb:
        return sb
    else:
        raise PrerequisiteError(
            dedent("""
                The computer tool service was not found in any of the sandboxes for this sample. Please add the computer tool service to your configuration. For example, the following Docker compose file uses the aisiuk/inspect-computer-tool image as its default sandbox:

                services:
                  default:
                    image: "aisiuk/inspect-computer-tool"
                    init: true
                """).strip()
        )
