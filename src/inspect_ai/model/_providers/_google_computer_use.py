from google.genai.types import (
    ComputerUse,
    Environment,
    FunctionCall,
    FunctionResponseBlob,
    FunctionResponsePart,
    Tool,
)
from shortuuid import uuid

from inspect_ai._util.content import ContentImage
from inspect_ai._util.images import file_as_data
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tools._computer import is_builtin_computer_tool

# Default display dimensions matching MAX_SCALING_TARGETS["FWXGA"] in _x11_client.py.
# These should stay in sync with the dimensions used by the container.
DISPLAY_WIDTH = 1366
DISPLAY_HEIGHT = 768


def maybe_computer_use_tool(model_name: str, tool: ToolInfo) -> Tool | None:
    return (
        Tool(
            computer_use=ComputerUse(
                environment=Environment.ENVIRONMENT_BROWSER,
            )
        )
        if (
            "gemini-2.5-computer-use-preview" in model_name
            or "gemini-3-pro-preview" in model_name
            or "gemini-3-flash-preview" in model_name
        )
        and is_builtin_computer_tool(tool)
        else None
    )


def tool_call_from_gemini_computer_action(
    function_call: FunctionCall,
) -> ToolCall:
    name = function_call.name or ""
    return ToolCall(
        id=f"{name}_{uuid()}",
        function="computer",
        arguments=_parse_gemini_action(name, function_call.args or {}),
    )


async def computer_tool_result_parts(
    message: ChatMessageTool,
) -> list[FunctionResponsePart]:
    parts: list[FunctionResponsePart] = []
    if isinstance(message.content, list):
        for item in message.content:
            if isinstance(item, ContentImage):
                image_bytes, mime_type = await file_as_data(item.image)
                parts.append(
                    FunctionResponsePart(
                        inline_data=FunctionResponseBlob(
                            mime_type=mime_type, data=image_bytes
                        )
                    )
                )
    return parts


def gemini_action_from_tool_call(
    tool_call: ToolCall,
) -> tuple[str, dict[str, object]]:
    arguments = tool_call.arguments
    action = str(arguments.get("action", ""))

    if action == "left_click":
        x, y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return "click_at", {"x": x, "y": y}

    elif action == "mouse_move":
        x, y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return "hover_at", {"x": x, "y": y}

    elif action == "key":
        text = str(arguments.get("text", ""))
        mapping = {
            "Return": "enter",
            "Escape": "escape",
            "BackSpace": "backspace",
            "Tab": "tab",
            "space": "space",
            "Delete": "delete",
            "Home": "home",
            "End": "end",
            "Prior": "pageup",
            "Next": "pagedown",
            "Up": "up",
            "Down": "down",
            "Left": "left",
            "Right": "right",
            "ctrl": "control",
            "shift": "shift",
            "alt": "alt",
        }
        keys = "+".join(mapping.get(p.strip(), p.strip()) for p in text.split("+"))
        return "key_combination", {"keys": keys}

    elif action == "type":
        text = str(arguments.get("text", ""))
        coordinate = arguments.get("coordinate")
        if coordinate:
            x, y = _normalize_coordinate(coordinate)
        else:
            x, y = 0, 0
        return "type_text_at", {"text": text, "x": x, "y": y}

    elif action == "scroll":
        direction = str(arguments.get("scroll_direction", "down"))
        coordinate = arguments.get("coordinate")
        if coordinate:
            x, y = _normalize_coordinate(coordinate)
            amount = int(str(arguments.get("scroll_amount", 3)))
            magnitude = min(amount * 100, 999)
            return "scroll_at", {
                "x": x,
                "y": y,
                "direction": direction,
                "magnitude": magnitude,
            }
        return "scroll_document", {"direction": direction}

    elif action == "left_click_drag":
        start_x, start_y = _normalize_coordinate(
            arguments.get("start_coordinate", [0, 0])
        )
        end_x, end_y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return "drag_and_drop", {
            "x": start_x,
            "y": start_y,
            "destination_x": end_x,
            "destination_y": end_y,
        }

    elif action == "wait":
        return "wait_5_seconds", {}

    elif action == "open_web_browser":
        return "open_web_browser", {}

    elif action == "navigate":
        text = str(arguments.get("text", ""))
        return "navigate", {"url": text}

    else:
        # Best-effort: actions without Gemini equivalents (screenshot,
        # triple_click, cursor_position, etc.) map to wait_5_seconds
        # as a no-op that still returns a screenshot.
        return "wait_5_seconds", {}


def _parse_gemini_action(name: str, args: dict[str, object]) -> dict[str, object]:
    if name == "click_at":
        x, y = _denormalize_coordinate(args)
        return {"action": "left_click", "coordinate": [x, y]}

    elif name == "type_text_at":
        x, y = _denormalize_coordinate(args)
        text = str(args.get("text", ""))
        return {"action": "type", "text": text, "coordinate": [x, y]}

    elif name == "hover_at":
        x, y = _denormalize_coordinate(args)
        return {"action": "mouse_move", "coordinate": [x, y]}

    elif name == "key_combination":
        keys = str(args.get("keys", ""))
        mapping = {
            "enter": "Return",
            "escape": "Escape",
            "backspace": "BackSpace",
            "tab": "Tab",
            "space": "space",
            "delete": "Delete",
            "home": "Home",
            "end": "End",
            "pageup": "Prior",
            "pagedown": "Next",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
            "control": "ctrl",
            "shift": "shift",
            "alt": "alt",
        }
        text = "+".join(
            mapping.get(p.strip().lower(), p.strip()) for p in keys.split("+")
        )
        return {"action": "key", "text": text}

    elif name == "scroll_document":
        direction = str(args.get("direction", "down"))
        return {
            "action": "scroll",
            "scroll_direction": direction,
            "scroll_amount": 3,
        }

    elif name == "scroll_at":
        x, y = _denormalize_coordinate(args)
        direction = str(args.get("direction", "down"))
        magnitude = int(str(args.get("magnitude", 800)))
        scroll_amount = max(1, magnitude // 100)
        return {
            "action": "scroll",
            "coordinate": [x, y],
            "scroll_direction": direction,
            "scroll_amount": scroll_amount,
        }

    elif name == "drag_and_drop":
        start_x, start_y = _denormalize_coordinate(args, x_key="x", y_key="y")
        end_x, end_y = _denormalize_coordinate(
            args, x_key="destination_x", y_key="destination_y"
        )
        return {
            "action": "left_click_drag",
            "start_coordinate": [start_x, start_y],
            "coordinate": [end_x, end_y],
        }

    elif name == "navigate":
        url = str(args.get("url", ""))
        return {"action": "navigate", "text": url}

    elif name == "go_back":
        return {"action": "key", "text": "alt+Left"}

    elif name == "go_forward":
        return {"action": "key", "text": "alt+Right"}

    elif name == "open_web_browser":
        return {"action": "open_web_browser"}

    elif name == "search":
        query = str(args.get("query", ""))
        return {"action": "navigate", "text": query}

    elif name == "wait_5_seconds":
        return {"action": "wait", "duration": 5}

    else:
        return {"action": "screenshot"}


def _denormalize_coordinate(
    args: dict[str, object],
    x_key: str = "x",
    y_key: str = "y",
) -> tuple[int, int]:
    x = int(str(args.get(x_key, 0)))
    y = int(str(args.get(y_key, 0)))
    return round(x / 1000 * DISPLAY_WIDTH), round(y / 1000 * DISPLAY_HEIGHT)


def _normalize_coordinate(
    coordinate: object,
) -> tuple[int, int]:
    if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2:
        x, y = int(coordinate[0]), int(coordinate[1])
        return round(x * 1000 / DISPLAY_WIDTH), round(y * 1000 / DISPLAY_HEIGHT)
    return 0, 0
