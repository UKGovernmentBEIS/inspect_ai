"""Google computer-action names without importing its optional SDK."""

from collections.abc import Mapping
from typing import Any


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
