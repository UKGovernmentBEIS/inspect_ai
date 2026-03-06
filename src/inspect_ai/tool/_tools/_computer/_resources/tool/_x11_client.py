"""Inspired by https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/computer_use_demo/tools/computer.py"""

import asyncio
import base64
import logging
import os
import shlex
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from _run import run
from _tool_result import ToolResult

OUTPUT_DIR = "/tmp/outputs"

TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

ColorCount = Literal[4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4]


class X11ClientError(Exception):
    def __init__(self, message):
        self.message = message


class Resolution(TypedDict):
    width: int
    height: int


# sizes above XGA/WXGA are not recommended (see README.md)
# scale down to one of these targets if ComputerTool._scaling_enabled is set
MAX_SCALING_TARGETS: dict[str, Resolution] = {
    "XGA": Resolution(width=1024, height=768),  # 4:3 - 1.33 - 768k pixels
    "WXGA": Resolution(width=1280, height=800),  # 16:10 - 1.60 -  1,000k pixels
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9 - 1.79 - 1,025k pixels
}


ScaleDirection = Literal["api_to_native", "native_to_api"]


class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None


def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]


class X11Client:
    """
    A tool that allows the agent to interact with the screen, keyboard, and mouse of the current computer.

    The tool parameters are defined by Anthropic and are not editable.
    """

    width: int
    height: int
    display_num: int | None
    # TODO: Complete plumbing this or remove it
    color_count: ColorCount | None = 256

    _screenshot_delay = 2.0
    _scaling_enabled = True

    @property
    def options(self) -> ComputerToolOptions:
        width, height = self._scale_coordinates(
            "native_to_api", self.width, self.height
        )
        return {
            "display_width_px": width,
            "display_height_px": height,
            "display_number": self.display_num,
        }

    def __init__(self):
        super().__init__()

        self.width = int(os.getenv("WIDTH") or 0)
        self.height = int(os.getenv("HEIGHT") or 0)
        assert self.width and self.height, "WIDTH, HEIGHT must be set"
        if (display_num := os.getenv("DISPLAY_NUM")) is not None:
            self.display_num = int(display_num)
            self._display_prefix = f"DISPLAY=:{self.display_num} "
        else:
            self.display_num = None
            self._display_prefix = ""

        self.xdotool = f"{self._display_prefix}xdotool"

    async def key(self, text: str) -> ToolResult:
        return await self._shell(f"{self.xdotool} key -- {_key_arg_for_text(text)}")

    async def hold_key(self, text: str, duration: int) -> ToolResult:
        key_arg = _key_arg_for_text(text)
        await self._shell(f"{self.xdotool} keydown -- {key_arg}", False)
        await asyncio.sleep(duration)
        return await self._shell(f"{self.xdotool} keyup -- {key_arg}")

    async def type(self, text: str) -> ToolResult:
        results: list[ToolResult] = []
        for chunk in chunks(text, TYPING_GROUP_SIZE):
            cmd = (
                f"{self.xdotool} type --delay {TYPING_DELAY_MS} -- {shlex.quote(chunk)}"
            )
            results.append(await self._shell(cmd, take_screenshot=False))

        screenshot_base64 = await self._take_screenshot_after_delay()
        return ToolResult(
            output="".join(result.output or "" for result in results),
            error="".join(result.error or "" for result in results),
            base64_image=screenshot_base64,
        )

    async def cursor_position(self) -> ToolResult:
        result = await self._shell(
            f"{self.xdotool} getmouselocation --shell",
            take_screenshot=False,
        )
        output = result.output or ""
        x, y = self._scale_coordinates(
            "native_to_api",
            int(output.split("X=")[1].split("\n")[0]),
            int(output.split("Y=")[1].split("\n")[0]),
        )
        return result.replace(output=f"X={x},Y={y}")

    async def left_mouse_down(self) -> ToolResult:
        return await self._shell(f"{self.xdotool} mousedown 1")

    async def left_mouse_up(self) -> ToolResult:
        return await self._shell(f"{self.xdotool} mouseup 1")

    async def mouse_move(self, coordinate: tuple[int, int]) -> ToolResult:
        return await self._mouse_move_and("mouse_move", coordinate, None)

    async def left_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("left_click", coordinate, text)

    async def right_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("right_click", coordinate, text)

    async def middle_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("middle_click", coordinate, text)

    # https://wiki.archlinux.org/title/Mouse_buttons#Thumb_buttons_-_forward_and_back
    # suggests that, although not in any spec, the de facto standard is 8 for
    # back and 9 for forward.
    async def back_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("back_click", coordinate, text)

    async def forward_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("forward_click", coordinate, text)

    async def double_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("double_click", coordinate, text)

    async def triple_click(
        self, coordinate: tuple[int, int] | None, text: str | None
    ) -> ToolResult:
        return await self._mouse_move_and("triple_click", coordinate, text)

    async def left_click_drag(
        self, start_coordinate: tuple[int, int], coordinate: tuple[int, int]
    ) -> ToolResult:
        await self._move_mouse_to_coordinate(start_coordinate, False)
        x, y = self._scale_coordinates("api_to_native", *coordinate)
        return await self._shell(
            f"{self.xdotool} mousedown 1 mousemove --sync {x} {y} mouseup 1"
        )

    async def scroll(
        self,
        scroll_direction: Literal["up", "down", "left", "right"],
        scroll_amount: int,
        coordinate: tuple[int, int] | None,
        text: str | None,
    ) -> ToolResult:
        if coordinate:
            await self._move_mouse_to_coordinate(coordinate, False)
        scroll_button = {
            "up": 4,
            "down": 5,
            "left": 6,
            "right": 7,
        }[scroll_direction]

        if text:
            key_arg = _key_arg_for_text(text)
            await self._shell(f"{self.xdotool} keydown -- {key_arg}", False)
            await self._shell(
                f"{self.xdotool} click --repeat {scroll_amount} {scroll_button}",
                False,
            )
            return await self._shell(f"{self.xdotool} keyup -- {key_arg}")
        else:
            return await self._shell(
                f"{self.xdotool} click --repeat {scroll_amount} {scroll_button}"
            )

    async def wait(self, duration: int) -> ToolResult:
        await asyncio.sleep(duration)
        return await self.screenshot()

    async def screenshot(self) -> ToolResult:
        return await self._screenshot()

    async def open_web_browser(self) -> ToolResult:
        """Open the web browser (Firefox) in full screen view."""
        await run(f"{self._display_prefix}firefox-esr --new-window >/dev/null 2>&1 &")
        # Wait for a visible Firefox window to appear, then activate it
        await run(f"{self.xdotool} search --sync --onlyvisible --class firefox-esr")
        await self._activate_browser()
        await run(f"{self.xdotool} key F11")
        await asyncio.sleep(1)
        return await self.screenshot()

    async def navigate(self, url: str) -> ToolResult:
        """Navigate to a URL in the browser."""
        await self._activate_browser()
        await run(f"{self.xdotool} key ctrl+l")
        await asyncio.sleep(0.5)
        await self.type(url)
        await run(f"{self.xdotool} key Return")
        await asyncio.sleep(1)
        return await self.screenshot()

    async def _activate_browser(self) -> None:
        """Find and activate the most recent Firefox window."""
        _, stdout, _ = await run(
            f"{self.xdotool} search --onlyvisible --class firefox-esr"
        )
        window_id = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        if window_id:
            await run(f"{self.xdotool} windowactivate --sync {window_id}")

    async def zoom(self, region: list[int]) -> ToolResult:
        """Take a zoomed screenshot of a specified region at native resolution."""
        if (
            len(region) != 4
            or any(r < 0 for r in region)
            or region[2] <= region[0]
            or region[3] <= region[1]
        ):
            raise X11ClientError("Invalid region")

        # Scale coordinates from API space to native screen space
        x0, y0 = self._scale_coordinates("api_to_native", region[0], region[1])
        x1, y1 = self._scale_coordinates("api_to_native", region[2], region[3])

        return await self._screenshot(zoom_region=(x0, y0, x1, y1))

    async def _mouse_move_and(
        self,
        action: Literal[
            "mouse_move",
            "left_click",
            "right_click",
            "middle_click",
            "back_click",
            "forward_click",
            "double_click",
            "triple_click",
        ],
        coordinate: tuple[int, int] | None,
        text: str | None,
    ):
        should_move = action == "mouse_move" or coordinate
        if should_move:
            assert coordinate  # coding/type safety error
            move_result = await self._move_mouse_to_coordinate(
                coordinate, action == "mouse_move"
            )
            if action == "mouse_move":
                return move_result
        click_arg = {
            "left_click": "1",
            "right_click": "3",
            "middle_click": "2",
            "back_click": "8",
            "forward_click": "9",
            "double_click": "--repeat 2 --delay 300 1",
            "triple_click": "--repeat 3 --delay 300 1",
        }[action]

        if text:
            key_arg = _key_arg_for_text(text)
            await self._shell(f"{self.xdotool} keydown -- {key_arg}", False)
            await self._shell(f"{self.xdotool} click {click_arg}", False)
            return await self._shell(f"{self.xdotool} keyup -- {key_arg}")
        else:
            return await self._shell(f"{self.xdotool} click {click_arg}")

    async def _move_mouse_to_coordinate(
        self, coordinate: tuple[int, int], take_screenshot: bool
    ):
        x, y = self._scale_coordinates("api_to_native", *coordinate)
        return await self._shell(
            f"{self.xdotool} mousemove --sync {x} {y}", take_screenshot=take_screenshot
        )

    async def _screenshot(
        self,
        zoom_region: tuple[int, int, int, int] | None = None,
    ) -> ToolResult:
        """Take a screenshot.

        Args:
            zoom_region: If provided, crop to native coords (x0, y0, x1, y1) at native
                resolution. If None, capture full screen scaled to API dimensions.
        """
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"

        result = await self._shell(
            f"{self._display_prefix}scrot --silent -p {path}", take_screenshot=False
        )

        # Build convert command with all needed operations
        convert_ops: list[str] = []
        if zoom_region:
            x0, y0, x1, y1 = zoom_region
            convert_ops.append(f"-crop {x1 - x0}x{y1 - y0}+{x0}+{y0} +repage")
        elif self._scaling_enabled:
            x, y = self._scale_coordinates("native_to_api", self.width, self.height)
            convert_ops.append(f"-resize {x}x{y}!")
        if self.color_count is not None:
            convert_ops.append(f"-colors {self.color_count}")

        if convert_ops:
            convert_cmd = f"convert {path} {' '.join(convert_ops)} {path}"
            await self._shell(convert_cmd, take_screenshot=False)

        if path.exists():
            return result.replace(
                base64_image=base64.b64encode(path.read_bytes()).decode()
            )
        raise X11ClientError(f"Failed to take screenshot: {result.error}")

    async def _shell(self, command: str, take_screenshot=True) -> ToolResult:
        """Run a shell command and return the output, error, and optionally a screenshot."""
        logging.debug(f"running shell command {command}")
        _, stdout, stderr = await run(command)
        logging.debug(f"shell command returned stdout: {stdout}, stderr: {stderr}")
        return ToolResult(
            output=stdout,
            error=stderr,
            base64_image=(await self._take_screenshot_after_delay())
            if take_screenshot
            else None,
        )

    async def _take_screenshot_after_delay(self) -> str:
        # delay to let things settle before taking a screenshot
        await asyncio.sleep(self._screenshot_delay)
        return (await self._screenshot()).base64_image

    def _scale_coordinates(self, direction: ScaleDirection, x: int, y: int):
        """Scale coordinates between API and native coordinate spaces.

        Args:
            direction: Conversion direction
                - "api_to_native": Scale UP for mouse actions (API → native)
                - "native_to_api": Scale DOWN for reporting (native → API)
            x: X coordinate
            y: Y coordinate
        """
        if not self._scaling_enabled:
            return x, y
        ratio = self.width / self.height
        target_dimension = None
        for dimension in MAX_SCALING_TARGETS.values():
            # allow some error in the aspect ratio - not ratios are exactly 16:9
            if abs(dimension["width"] / dimension["height"] - ratio) < 0.02:
                if dimension["width"] < self.width:
                    target_dimension = dimension
                break
        if target_dimension is None:
            return x, y
        # should be less than 1
        x_scaling_factor = target_dimension["width"] / self.width
        y_scaling_factor = target_dimension["height"] / self.height
        if direction == "api_to_native":
            if x > self.width or y > self.height:
                raise X11ClientError(f"Coordinates {x}, {y} are out of bounds")
            # scale up
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        # scale down
        return round(x * x_scaling_factor), round(y * y_scaling_factor)


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
# (e.g. "Enter" -> "Return").  _normalize_key_combo fuzzy-matches as a fallback.
# Modifiers (ctrl/alt/shift/super/meta) are already case-insensitive in xdotool
# so they're excluded.  Single characters are handled separately in
# _normalize_key_combo.
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
        # Modifier abbreviations — map to xdotool's built-in aliases
        "ctl": "ctrl",
        "control": "ctrl",
        "cmd": "super",
        "command": "super",
        "win": "super",
        "windows": "super",
        "opt": "alt",
        "option": "alt",
    }
)


def _normalize_key_combo(combo: str) -> str:
    """Normalize a key combo for xdotool.

    - Named keys are resolved via the alias table
    - Unrecognized keys pass through unchanged (xdotool will error, which goes
      back to the model)
    - In modifier combos (e.g. "ctrl+L"), single letters are lowercased because an
      uppercase letter would cause xdotool to implicitly add Shift, which is almost
      never the intent when a model writes e.g. "CTRL+L".
    """
    parts = combo.split("+")
    is_combo = len(parts) > 1
    normalized = []
    for part in parts:
        if len(part) == 1 and part.isalpha():
            # Single letter: lowercase when part of a combo to avoid implicit Shift
            normalized.append(part.lower() if is_combo else part)
        else:
            normalized.append(_KEY_ALIASES.get(part.lower(), part))
    return "+".join(normalized)


def _key_arg_for_text(text: str) -> str:
    return " ".join(shlex.quote(_normalize_key_combo(part)) for part in text.split())
