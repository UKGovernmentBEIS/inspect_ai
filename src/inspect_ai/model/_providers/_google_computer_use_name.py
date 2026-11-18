"""Google computer actions, by name and arguments, without importing its optional SDK."""

from collections.abc import Mapping
from typing import Any

from inspect_ai.tool._tool_call import ToolCall

# Default display dimensions matching MAX_SCALING_TARGETS["FWXGA"] in _x11_client.py.
# These should stay in sync with the dimensions used by the container.
DISPLAY_WIDTH = 1366
DISPLAY_HEIGHT = 768


def gemini_computer_action_name(arguments: Mapping[str, Any]) -> str:
    """Return the function name Google sends for a computer action.

    Only the name: coordinates and scroll amounts are not parsed.
    """
    action = str(arguments.get("action", ""))
    if action == "left_click":
        return "click_at"
    if action == "mouse_move":
        return "hover_at"
    if action == "key":
        return "key_combination"
    if action == "type":
        return "type_text_at"
    if action == "scroll":
        return "scroll_at" if arguments.get("coordinate") else "scroll_document"
    if action == "left_click_drag":
        return "drag_and_drop"
    if action == "open_web_browser":
        return "open_web_browser"
    if action == "navigate":
        return "navigate"
    return "wait_5_seconds"


GEMINI_COMPUTER_ACTIONS = frozenset(
    {
        "click_at",
        "type_text_at",
        "hover_at",
        "key_combination",
        "scroll_document",
        "scroll_at",
        "drag_and_drop",
        "navigate",
        "go_back",
        "go_forward",
        "open_web_browser",
        "search",
        "wait_5_seconds",
    }
)


def gemini_computer_action_names(arguments: Mapping[str, Any]) -> frozenset[str]:
    """The function names Google can have sent for a computer action.

    `go_back`, `go_forward` and `search` are parsed as other actions.
    """
    names = {gemini_computer_action_name(arguments)}
    action = arguments.get("action")
    if action == "key" and arguments.get("text") == "alt+Left":
        names.add("go_back")
    elif action == "key" and arguments.get("text") == "alt+Right":
        names.add("go_forward")
    elif action == "navigate":
        names.add("search")
    return frozenset(names)


def gemini_action_from_tool_call(
    tool_call: ToolCall,
) -> tuple[str, dict[str, object]]:
    arguments = tool_call.arguments
    action = str(arguments.get("action", ""))
    name = gemini_computer_action_name(arguments)

    if action == "left_click":
        x, y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return name, {"x": x, "y": y}

    elif action == "mouse_move":
        x, y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return name, {"x": x, "y": y}

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
        return name, {"keys": keys}

    elif action == "type":
        text = str(arguments.get("text", ""))
        x, y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        result: dict[str, object] = {"text": text, "x": x, "y": y}
        if "press_enter" in arguments:
            result["press_enter"] = bool(arguments["press_enter"])
        # Gemini defaults clear_before_typing to True, so send False explicitly
        result["clear_before_typing"] = bool(arguments.get("clear_before_typing"))
        return name, result

    elif action == "scroll":
        direction = str(arguments.get("scroll_direction", "down"))
        coordinate = arguments.get("coordinate")
        if coordinate:
            x, y = _normalize_coordinate(coordinate)
            amount = int(str(arguments.get("scroll_amount", 3)))
            magnitude = min(amount * 100, 999)
            return name, {
                "x": x,
                "y": y,
                "direction": direction,
                "magnitude": magnitude,
            }
        return name, {"direction": direction}

    elif action == "left_click_drag":
        start_x, start_y = _normalize_coordinate(
            arguments.get("start_coordinate", [0, 0])
        )
        end_x, end_y = _normalize_coordinate(arguments.get("coordinate", [0, 0]))
        return name, {
            "x": start_x,
            "y": start_y,
            "destination_x": end_x,
            "destination_y": end_y,
        }

    elif action == "wait":
        return name, {}

    elif action == "open_web_browser":
        return name, {}

    elif action == "navigate":
        text = str(arguments.get("text", ""))
        return name, {"url": text}

    else:
        # Best-effort: actions without Gemini equivalents (screenshot,
        # triple_click, cursor_position, etc.) map to wait_5_seconds
        # as a no-op that still returns a screenshot.
        return name, {}


def _normalize_coordinate(
    coordinate: object,
) -> tuple[int, int]:
    if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2:
        x, y = int(coordinate[0]), int(coordinate[1])
        return round(x * 1000 / DISPLAY_WIDTH), round(y * 1000 / DISPLAY_HEIGHT)
    return 0, 0
