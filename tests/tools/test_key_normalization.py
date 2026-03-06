"""Tests for xdotool key name normalization in _x11_client.py."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Stub out container-only modules so we can import _x11_client in the test env.
for _mod_name in ("_run", "_tool_result"):
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        if _mod_name == "_run":
            _stub.run = MagicMock()  # type: ignore
        elif _mod_name == "_tool_result":
            _stub.ToolResult = type("ToolResult", (), {})  # type: ignore
        sys.modules[_mod_name] = _stub

# Import the module directly by file path to avoid circular import through the
# inspect_ai package tree.
_MODULE_PATH = Path(__file__).resolve().parents[2] / (
    "src/inspect_ai/tool/_tools/_computer/_resources/tool/_x11_client.py"
)
_spec = importlib.util.spec_from_file_location("_x11_client", _MODULE_PATH)
assert _spec and _spec.loader
_x11_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_x11_client)

_normalize_key_combo = _x11_client._normalize_key_combo
_key_arg_for_text = _x11_client._key_arg_for_text


# -- Single key normalization (keysym casing + model-vocabulary aliases) --


@pytest.mark.parametrize(
    "input_key,expected",
    [
        # Return / Enter
        ("Return", "Return"),
        ("return", "Return"),
        ("RETURN", "Return"),
        ("Enter", "Return"),
        ("enter", "Return"),
        ("ENTER", "Return"),
        # Escape / Esc
        ("Escape", "Escape"),
        ("escape", "Escape"),
        ("ESCAPE", "Escape"),
        ("Esc", "Escape"),
        ("esc", "Escape"),
        ("ESC", "Escape"),
        # BackSpace
        ("BackSpace", "BackSpace"),
        ("backspace", "BackSpace"),
        ("BACKSPACE", "BackSpace"),
        # Tab
        ("Tab", "Tab"),
        ("tab", "Tab"),
        ("TAB", "Tab"),
        # Delete
        ("Delete", "Delete"),
        ("delete", "Delete"),
        # Insert
        ("Insert", "Insert"),
        # Home / End
        ("Home", "Home"),
        ("home", "Home"),
        ("End", "End"),
        ("end", "End"),
        # Prior/Next (PageUp/PageDown)
        ("Prior", "Prior"),
        ("prior", "Prior"),
        ("PageUp", "Prior"),
        ("pageup", "Prior"),
        ("PAGEUP", "Prior"),
        ("Next", "Next"),
        ("next", "Next"),
        ("PageDown", "Next"),
        ("pagedown", "Next"),
        ("PAGEDOWN", "Next"),
        # Arrow keys
        ("Left", "Left"),
        ("left", "Left"),
        ("ArrowLeft", "Left"),
        ("arrowleft", "Left"),
        ("ARROWLEFT", "Left"),
        ("Up", "Up"),
        ("up", "Up"),
        ("ArrowUp", "Up"),
        ("arrowup", "Up"),
        ("ARROWUP", "Up"),
        ("Right", "Right"),
        ("right", "Right"),
        ("ArrowRight", "Right"),
        ("arrowright", "Right"),
        ("ARROWRIGHT", "Right"),
        ("Down", "Down"),
        ("down", "Down"),
        ("ArrowDown", "Down"),
        ("arrowdown", "Down"),
        ("ARROWDOWN", "Down"),
        # Misc
        ("Pause", "Pause"),
        ("pause", "Pause"),
        ("space", "space"),
        # Function keys (representative: first, middle, last)
        ("F1", "F1"),
        ("f1", "F1"),
        ("F5", "F5"),
        ("f5", "F5"),
        ("F12", "F12"),
        ("f12", "F12"),
        # Modifier keysyms as standalone keys
        ("Shift_L", "Shift_L"),
        ("shift_l", "Shift_L"),
        ("Shift_R", "Shift_R"),
        ("Control_L", "Control_L"),
        ("control_l", "Control_L"),
        ("Control_R", "Control_R"),
        ("Alt_L", "Alt_L"),
        ("alt_l", "Alt_L"),
        ("Alt_R", "Alt_R"),
        # Numpad (representative sample)
        ("KP_Enter", "KP_Enter"),
        ("kp_enter", "KP_Enter"),
        ("KP_ENTER", "KP_Enter"),
        ("KP_0", "KP_0"),
        ("kp_0", "KP_0"),
        ("KP_Multiply", "KP_Multiply"),
        ("kp_multiply", "KP_Multiply"),
        ("KP_Home", "KP_Home"),
        ("KP_Decimal", "KP_Decimal"),
        ("kp_decimal", "KP_Decimal"),
        # Lock keys
        ("Scroll_Lock", "Scroll_Lock"),
        ("scroll_lock", "Scroll_Lock"),
        ("Num_Lock", "Num_Lock"),
        ("num_lock", "Num_Lock"),
        ("Caps_Lock", "Caps_Lock"),
        ("caps_lock", "Caps_Lock"),
    ],
)
def test_single_key(input_key: str, expected: str) -> None:
    assert _normalize_key_combo(input_key) == expected


# -- Standalone letters preserve case --


@pytest.mark.parametrize("letter", ["l", "L", "a", "A", "z", "Z"])
def test_standalone_letter_preserves_case(letter: str) -> None:
    assert _normalize_key_combo(letter) == letter


# -- Combos: modifier + letter lowercases the letter --


@pytest.mark.parametrize(
    "input_combo,expected",
    [
        ("ctrl+L", "ctrl+l"),
        ("ctrl+l", "ctrl+l"),
        ("CTRL+L", "CTRL+l"),
        ("alt+L", "alt+l"),
        ("ctrl+shift+T", "ctrl+shift+t"),
        ("ctrl+shift+t", "ctrl+shift+t"),
    ],
)
def test_modifier_combo_lowercases_letter(input_combo: str, expected: str) -> None:
    assert _normalize_key_combo(input_combo) == expected


# -- Combos: modifier + named key --


@pytest.mark.parametrize(
    "input_combo,expected",
    [
        ("ctrl+return", "ctrl+Return"),
        ("ctrl+Return", "ctrl+Return"),
        ("ctrl+enter", "ctrl+Return"),
        ("alt+tab", "alt+Tab"),
        ("alt+Tab", "alt+Tab"),
        ("ctrl+backspace", "ctrl+BackSpace"),
        ("ctrl+esc", "ctrl+Escape"),
        ("ctrl+s", "ctrl+s"),
    ],
)
def test_named_key_in_combo(input_combo: str, expected: str) -> None:
    assert _normalize_key_combo(input_combo) == expected


# -- Modifier aliases --


@pytest.mark.parametrize(
    "input_combo,expected",
    [
        # ctl -> ctrl
        ("ctl+c", "ctrl+c"),
        ("CTL+c", "ctrl+c"),
        # control -> ctrl
        ("control+c", "ctrl+c"),
        ("Control+c", "ctrl+c"),
        ("CONTROL+c", "ctrl+c"),
        # cmd -> super
        ("cmd+c", "super+c"),
        ("CMD+c", "super+c"),
        # command -> super
        ("command+c", "super+c"),
        ("Command+c", "super+c"),
        # win -> super
        ("win+c", "super+c"),
        ("Win+c", "super+c"),
        # windows -> super
        ("windows+c", "super+c"),
        ("Windows+c", "super+c"),
        # opt -> alt
        ("opt+c", "alt+c"),
        ("Opt+c", "alt+c"),
        # option -> alt
        ("option+c", "alt+c"),
        ("Option+c", "alt+c"),
    ],
)
def test_modifier_aliases(input_combo: str, expected: str) -> None:
    assert _normalize_key_combo(input_combo) == expected


# -- Unknown keys pass through --


def test_unknown_passthrough() -> None:
    assert _normalize_key_combo("xyzzy123") == "xyzzy123"
    assert _normalize_key_combo("ctrl+xyzzy123") == "ctrl+xyzzy123"


# -- _key_arg_for_text (space-separated multi-key sequences) --


@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("Return", "Return"),
        ("return", "Return"),
        ("ctrl+L", "ctrl+l"),
        ("ctrl+L Return", "ctrl+l Return"),
    ],
)
def test_key_arg_for_text(input_text: str, expected: str) -> None:
    assert _key_arg_for_text(input_text) == expected
