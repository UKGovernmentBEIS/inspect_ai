"""Host-mode backend for the computer tool.

Executes desktop actions directly on the host machine using pyautogui
and mss/PIL for screenshots, instead of inside a Docker sandbox.

This module provides the same public API as ``_common.py`` so the
dispatch logic in ``_computer.py`` can swap between sandbox and host
backends transparently.

Requires: ``pip install pyautogui mss Pillow``
"""

from __future__ import annotations

import asyncio
import base64
import io
import platform
import time
from typing import Literal

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model import ContentImage
from inspect_ai.tool import ToolError, ToolResult

from ._common import ContentText

try:
    import pyautogui

    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None  # type: ignore[assignment]

try:
    import mss as _mss
except ImportError:
    _mss = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


def _require_deps() -> None:
    missing: list[str] = []
    if pyautogui is None:
        missing.append("pyautogui")
    if _mss is None:
        missing.append("mss")
    if Image is None:
        missing.append("Pillow")
    if missing:
        raise PrerequisiteError(
            f"Host-mode computer tool requires: {', '.join(missing)}. "
            f"Install with: pip install {' '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

_SCREENSHOT_DELAY = 1.5  # seconds – let UI settle before capture


async def _take_screenshot() -> str:
    """Capture the primary monitor and return a base64-encoded PNG."""
    _require_deps()

    def _grab() -> str:
        with _mss.mss() as sct:  # type: ignore[union-attr]
            raw = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", raw.size, raw.rgb)  # type: ignore[union-attr]
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    return await asyncio.get_event_loop().run_in_executor(None, _grab)


async def _screenshot_after_delay() -> str:
    await asyncio.sleep(_SCREENSHOT_DELAY)
    return await _take_screenshot()


def _make_result(
    output: str | None = None,
    *,
    with_screenshot: bool = True,
    base64_image: str | None = None,
) -> ToolResult:
    """Build a ToolResult, optionally including a screenshot."""
    parts: list[ContentText | ContentImage] = []
    if output:
        parts.append(ContentText(text=output))
    if base64_image:
        parts.append(ContentImage(image=f"data:image/png;base64,{base64_image}"))
    if not parts:
        return "OK"
    if len(parts) == 1:
        return parts[0].text if isinstance(parts[0], ContentText) else [parts[0]]
    return parts  # type: ignore[return-value]


async def _result_with_screenshot(output: str | None = None) -> ToolResult:
    img = await _screenshot_after_delay()
    return _make_result(output, base64_image=img)


# ---------------------------------------------------------------------------
# Key mapping – translate xdotool key names to pyautogui key names
# ---------------------------------------------------------------------------

_KEY_MAP: dict[str, str] = {
    "Return": "enter",
    "Escape": "escape",
    "BackSpace": "backspace",
    "Tab": "tab",
    "Delete": "delete",
    "Insert": "insert",
    "Home": "home",
    "End": "end",
    "Prior": "pageup",
    "Next": "pagedown",
    "Left": "left",
    "Up": "up",
    "Right": "right",
    "Down": "down",
    "space": "space",
    "Scroll_Lock": "scrolllock",
    "Num_Lock": "numlock",
    "Caps_Lock": "capslock",
    "Pause": "pause",
    "Shift_L": "shiftleft",
    "Shift_R": "shiftright",
    "Control_L": "ctrlleft",
    "Control_R": "ctrlright",
    "Alt_L": "altleft",
    "Alt_R": "altright",
    "Super_L": "winleft",
    "Super_R": "winright",
    "Print": "printscreen",
    # Modifiers (used in combos like "ctrl+s")
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "win" if platform.system() == "Windows" else "command",
    "meta": "win" if platform.system() == "Windows" else "command",
}

# Function keys
for _i in range(1, 13):
    _KEY_MAP[f"F{_i}"] = f"f{_i}"


def _translate_key(name: str) -> str:
    """Map an xdotool keysym name to a pyautogui key name."""
    return _KEY_MAP.get(name, name.lower())


def _parse_combo(combo: str) -> list[str]:
    """Parse 'ctrl+shift+s' into ['ctrl', 'shift', 's'] with mapped names."""
    return [_translate_key(p) for p in combo.split("+")]


# ---------------------------------------------------------------------------
# Public action functions – mirror _common.py signatures
# ---------------------------------------------------------------------------


async def cursor_position(timeout: int | None = None) -> ToolResult:
    _require_deps()
    pos = pyautogui.position()  # type: ignore[union-attr]
    return _make_result(f"X={pos.x},Y={pos.y}", with_screenshot=False)


async def screenshot(timeout: int | None = None) -> ToolResult:
    _require_deps()
    img = await _take_screenshot()
    return _make_result(base64_image=img)


async def wait(duration: int, timeout: int | None = None) -> ToolResult:
    await asyncio.sleep(duration)
    return await screenshot()


async def mouse_move(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.moveTo(coordinate[0], coordinate[1])  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def left_mouse_down(timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.mouseDown()  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def left_mouse_up(timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.mouseUp()  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def left_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.click(coordinate[0], coordinate[1])  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def left_click_drag(
    start_coordinate: list[int], coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    _require_deps()
    pyautogui.moveTo(start_coordinate[0], start_coordinate[1])  # type: ignore[union-attr]
    pyautogui.mouseDown()  # type: ignore[union-attr]
    pyautogui.moveTo(coordinate[0], coordinate[1], duration=0.3)  # type: ignore[union-attr]
    pyautogui.mouseUp()  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def right_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.click(coordinate[0], coordinate[1], button="right")  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def middle_click(
    coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    _require_deps()
    pyautogui.click(coordinate[0], coordinate[1], button="middle")  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def back_click(coordinate: list[int], timeout: int | None = None) -> ToolResult:
    # pyautogui doesn't directly support back/forward mouse buttons.
    # Fall back to move + xdotool-style button if on Linux, else raise.
    raise ToolError("back_click is not supported in host mode")


async def forward_click(
    coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    raise ToolError("forward_click is not supported in host mode")


async def double_click(
    coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    _require_deps()
    pyautogui.doubleClick(coordinate[0], coordinate[1])  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def triple_click(
    coordinate: list[int], timeout: int | None = None
) -> ToolResult:
    _require_deps()
    pyautogui.tripleClick(coordinate[0], coordinate[1])  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def scroll(
    scroll_amount: int,
    scroll_direction: Literal["up", "down", "left", "right"],
    coordinate: list[int] | None,
    timeout: int | None = None,
) -> ToolResult:
    _require_deps()
    if coordinate:
        pyautogui.moveTo(coordinate[0], coordinate[1])  # type: ignore[union-attr]

    if scroll_direction in ("up", "down"):
        amount = scroll_amount if scroll_direction == "up" else -scroll_amount
        pyautogui.scroll(amount)  # type: ignore[union-attr]
    else:
        amount = -scroll_amount if scroll_direction == "left" else scroll_amount
        pyautogui.hscroll(amount)  # type: ignore[union-attr]

    return await _result_with_screenshot()


async def press_key(key: str, timeout: int | None = None) -> ToolResult:
    _require_deps()
    # key may be space-separated combos like "ctrl+s"
    for combo in key.split():
        keys = _parse_combo(combo)
        if len(keys) == 1:
            pyautogui.press(keys[0])  # type: ignore[union-attr]
        else:
            pyautogui.hotkey(*keys)  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def hold_key(key: str, duration: int, timeout: int | None = None) -> ToolResult:
    _require_deps()
    keys = _parse_combo(key)
    for k in keys:
        pyautogui.keyDown(k)  # type: ignore[union-attr]
    await asyncio.sleep(duration)
    for k in reversed(keys):
        pyautogui.keyUp(k)  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def type(text: str, timeout: int | None = None) -> ToolResult:
    _require_deps()
    pyautogui.typewrite(text, interval=0.012)  # type: ignore[union-attr]
    return await _result_with_screenshot()


async def zoom(region: list[int], timeout: int | None = None) -> ToolResult:
    """Take a zoomed screenshot of a region [x0, y0, x1, y1]."""
    _require_deps()

    def _grab_region() -> str:
        with _mss.mss() as sct:  # type: ignore[union-attr]
            monitor = {
                "left": region[0],
                "top": region[1],
                "width": region[2] - region[0],
                "height": region[3] - region[1],
            }
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.rgb)  # type: ignore[union-attr]
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    b64 = await asyncio.get_event_loop().run_in_executor(None, _grab_region)
    return _make_result(base64_image=b64)


async def open_web_browser(timeout: int | None = None) -> ToolResult:
    """Open the default web browser. Platform-dependent."""
    import subprocess
    import webbrowser

    webbrowser.open("about:blank")
    await asyncio.sleep(2)
    return await screenshot()


async def navigate(text: str, timeout: int | None = None) -> ToolResult:
    """Navigate to a URL by typing it into the address bar."""
    _require_deps()
    # Ctrl+L / Cmd+L to focus address bar
    if platform.system() == "Darwin":
        pyautogui.hotkey("command", "l")  # type: ignore[union-attr]
    else:
        pyautogui.hotkey("ctrl", "l")  # type: ignore[union-attr]
    await asyncio.sleep(0.5)
    pyautogui.typewrite(text, interval=0.012)  # type: ignore[union-attr]
    pyautogui.press("enter")  # type: ignore[union-attr]
    await asyncio.sleep(1)
    return await screenshot()
