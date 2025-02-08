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


class ToolExecResult(BaseModel):
    output: str | None = Field(default=None)
    error: str | None = Field(default=None)
    base64_image: str | None = Field(default=None)


async def _send_cmd(cmdTail: list[str], timeout: int | None = None) -> ToolResult:
    from inspect_ai.log._samples import sample_active

    sample = sample_active()
    assert sample
    sample_id = sample.sample.id
    assert sample_id

    cmd = ["python3", "/opt/inspect/tool/computer_tool.py", "--action"] + cmdTail

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


async def cursor_position(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["cursor_position"], timeout=timeout)


async def screenshot(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["screenshot"], timeout=timeout)


async def mouse_move(x: int, y: int, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["mouse_move", "--coordinate", f"{x}", f"{y}"], timeout=timeout
    )


async def left_click(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["left_click"], timeout=timeout)


async def left_click_drag(x: int, y: int, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(
        ["left_click_drag", "--coordinate", f"{x}", f"{y}"], timeout=timeout
    )


async def right_click(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["right_click"], timeout=timeout)


async def middle_click(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["middle_click"], timeout=timeout)


async def double_click(timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["double_click"], timeout=timeout)


async def press_key(key: str, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["key", "--text", key], timeout=timeout)


async def type(text: str, timeout: int | None = None) -> ToolResult:
    return await _send_cmd(["type", "--text", text], timeout=timeout)


async def computer_sandbox() -> SandboxEnvironment:
    sb = await sandbox_with("/opt/inspect/tool/computer_tool.py")
    if sb:
        return sb
    else:
        raise PrerequisiteError(
            dedent("""
                The computer tool service was not found in any of the sandboxes for this sample. Please add the computer tool service to your configuration. For example, the following Docker compose file uses the aisiuk/inspect-computer-tool:latest-beta image as its default sandbox:

                services:
                  default:
                    image: "aisiuk/inspect-computer-tool:latest-beta"
                    init: true
                """).strip()
        )
