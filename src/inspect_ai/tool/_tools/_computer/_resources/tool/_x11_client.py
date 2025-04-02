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
    "XGA": Resolution(width=1024, height=768),  # 4:3
    "WXGA": Resolution(width=1280, height=800),  # 16:10
    "FWXGA": Resolution(width=1366, height=768),  # ~16:9
}


ScalingSource = Literal["computer", "api"]


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
        width, height = self._scale_coordinates("computer", self.width, self.height)
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
            "computer",
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
        x, y = self._scale_coordinates("api", *coordinate)
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
        x, y = self._scale_coordinates("api", *coordinate)
        return await self._shell(
            f"{self.xdotool} mousemove --sync {x} {y}", take_screenshot=take_screenshot
        )

    async def _screenshot(self):
        """Take a screenshot of the current screen and return the base64 encoded image."""
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"screenshot_{uuid4().hex}.png"

        result = await self._shell(
            f"{self._display_prefix}scrot --silent -p {path}", take_screenshot=False
        )
        if self._scaling_enabled:
            x, y = self._scale_coordinates("computer", self.width, self.height)
            convert_cmd = f"convert {path} -resize {x}x{y}!"
            if self.color_count is not None:
                convert_cmd += f" -colors {self.color_count}"
            convert_cmd += f" {path}"
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

    def _scale_coordinates(self, source: ScalingSource, x: int, y: int):
        """Scale coordinates to a target maximum resolution."""
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
        if source == "api":
            if x > self.width or y > self.height:
                raise X11ClientError(f"Coordinates {x}, {y} are out of bounds")
            # scale up
            return round(x / x_scaling_factor), round(y / y_scaling_factor)
        # scale down
        return round(x * x_scaling_factor), round(y * y_scaling_factor)


def _key_arg_for_text(text: str) -> str:
    return " ".join(shlex.quote(part) for part in text.split())
