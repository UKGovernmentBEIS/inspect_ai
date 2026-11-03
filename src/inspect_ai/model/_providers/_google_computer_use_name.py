"""Google computer-action names without importing its optional SDK."""

from collections.abc import Mapping
from typing import Any


def gemini_computer_action_name(arguments: Mapping[str, Any]) -> str:
    """Return the function name Google sends for a computer action.

    Token reservation needs only the name. In particular, it must not parse
    coordinates or scroll amounts for a call routed to another provider.
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
