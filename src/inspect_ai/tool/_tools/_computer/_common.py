import asyncio
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from inspect_ai._util.content import ContentText
from inspect_ai.model import ContentImage
from inspect_ai.tool import ToolError, ToolResult
from inspect_ai.util import sandbox

from ._mock_logger import MockLogger

Action = Literal[
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "screenshot",
    "cursor_position",
]

# log = logging.getLogger(__name__)
log = MockLogger()
log.setLevel(logging.DEBUG)


class ToolExecResult(BaseModel):
    output: str | None = Field(default=None)
    error: str | None = Field(default=None)
    base64_image: str | None = Field(default=None)


hackIsFirstCommand = True


async def _send_cmd(cmdTail: list[str]) -> ToolResult:
    # TODO: Resolve this issue
    # without this delay, the first attempt to take a screenshot
    # happens too soon before the GUI has actually rendered.
    global hackIsFirstCommand
    if hackIsFirstCommand:
        stallResult = await sandbox().exec(["whoami"])
        if not stallResult.success:
            log.error(f"First sandbox().exec() failed with: {stallResult.stderr}")
            raise ToolError(f"Error executing command: {stallResult.stderr}")
        log.debug(f"First sandbox().exec() succeeded {stallResult.stdout}...sleeping")
        await asyncio.sleep(20)
        log.debug("Stall done")
        hackIsFirstCommand = False

    cmd = ["python3", "/opt/computer_tool/computer_tool.py", "--action"] + cmdTail
    log.debug(f"Executing command: {cmd}")

    try:
        raw_exec_result = await sandbox().exec(cmd)

        if not raw_exec_result.success:
            raise Exception(
                f"Failure executing command: ${cmd} {raw_exec_result.stderr}"
            )

        result = ToolExecResult(**json.loads(raw_exec_result.stdout))

        if result.error:
            log.debug(f"Tool returned an error. Raising ToolError('{result.error}'")
            raise ToolError(result.error)

        image = (
            ContentImage(image=f"data:image/png;base64,{result.base64_image}")
            if result.base64_image
            else None
        )
        text = result.output if result.output and len(result.output) > 0 else None

        if text is not None and image is not None:
            log.debug(f"ToolResult([ContentText('{text}'), ContentImage])")
            return [ContentText(text=text), image]

        if text is not None:
            log.debug(f"ToolResult('{text}')")
            return text

        if image is not None:
            log.debug("ToolResult([ContentImage])")
            return [image]

        log.debug("Tool returned neither output nor image - returning ToolResult('OK')")
        return "OK"
    except ToolError:
        raise
    except Exception as e:
        log.error(f"Sandbox.exec threw for {cmd}...re-raising")
        raise e


async def cursor_position() -> ToolResult:
    return await _send_cmd(["cursor_position"])


async def screenshot() -> ToolResult:
    return await _send_cmd(["screenshot"])


async def mouse_move(x: int, y: int) -> ToolResult:
    return await _send_cmd(["mouse_move", "--coordinate", f"{x}", f"{y}"])


async def left_click() -> ToolResult:
    return await _send_cmd(["left_click"])


async def left_click_drag(x: int, y: int) -> ToolResult:
    return await _send_cmd(["left_click_drag", "--coordinate", f"{x}", f"{y}"])


async def right_click() -> ToolResult:
    return await _send_cmd(["right_click"])


async def middle_click() -> ToolResult:
    return await _send_cmd(["middle_click"])


async def double_click() -> ToolResult:
    return await _send_cmd(["double_click"])


async def press_key(key: str) -> ToolResult:
    # TODO: Temporary partial fix for lack of escaping of user input
    # When the model wants to key "*", it turns into a command line
    # ending in "-- *", which expands to a list of all files and folders
    # and hilarity ensues
    if key == "*":
        key = "KP_Multiply"
    res = await _send_cmd(["key", "--text", key])
    return res


async def type(text: str) -> ToolResult:
    return await _send_cmd(["type", "--text", text])
