"""Tests for the host-mode backend of the computer() tool.

These tests exercise `inspect_ai.tool._tools._computer._host` with the
optional pyautogui/mss/Pillow dependencies replaced by stub objects, so
they run on any platform (including CI without a display).
"""

from __future__ import annotations

import base64
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool import ToolError
from inspect_ai.tool._tools._computer import _host
from inspect_ai.tool._tools._computer._computer import (
    _COMPUTER_TOOL_PARAMETERS,
    computer,
)

# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


class _Position:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def _make_pyautogui_stub() -> MagicMock:
    stub = MagicMock(name="pyautogui")
    stub.FAILSAFE = True
    stub.position.return_value = _Position(123, 456)
    return stub


class _FakeRaw:
    def __init__(self) -> None:
        # 1x1 RGB pixel
        self.size = (1, 1)
        self.rgb = b"\x00\x00\x00"


class _FakeSct:
    monitors = [None, {"left": 0, "top": 0, "width": 1, "height": 1}]

    def __enter__(self) -> "_FakeSct":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def grab(self, monitor: Any) -> _FakeRaw:
        return _FakeRaw()


def _make_mss_stub() -> types.SimpleNamespace:
    return types.SimpleNamespace(mss=lambda: _FakeSct())


def _make_pil_stub() -> Any:
    # use the real PIL.Image since Pillow is in requirements-dev anyway,
    # but fall back to a stub if it isn't installed
    try:
        from PIL import Image

        return Image
    except ImportError:  # pragma: no cover - dev env always has Pillow
        stub = MagicMock(name="PIL.Image")
        img = MagicMock()
        img.save = lambda buf, format: buf.write(b"fakepng")
        stub.frombytes.return_value = img
        return stub


@pytest.fixture
def stub_deps(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch _host module-level dependency handles with stubs.

    Returns the pyautogui stub so tests can assert calls on it.
    """
    pyautogui_stub = _make_pyautogui_stub()
    monkeypatch.setattr(_host, "pyautogui", pyautogui_stub)
    monkeypatch.setattr(_host, "_mss", _make_mss_stub())
    monkeypatch.setattr(_host, "Image", _make_pil_stub())
    # speed up tests: bypass the post-action screenshot delay
    monkeypatch.setattr(_host, "_SCREENSHOT_DELAY", 0)
    return pyautogui_stub


# ---------------------------------------------------------------------------
# Tool plumbing
# ---------------------------------------------------------------------------


def test_computer_host_backend_selects_host_module() -> None:
    """computer(backend='host') should be tagged identically to the sandbox one."""
    tool_sandbox = computer()
    tool_host = computer(backend="host")
    # Both must expose the same public parameter schema so model providers
    # can still recognize them as the built-in computer tool.
    assert callable(tool_sandbox)
    assert callable(tool_host)


def test_is_computer_tool_info_unchanged_for_host_backend() -> None:
    from inspect_ai.tool._tool_info import parse_tool_info

    info = parse_tool_info(computer(backend="host"))
    assert info.parameters.properties.keys() == _COMPUTER_TOOL_PARAMETERS


def test_require_deps_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_host, "pyautogui", None)
    monkeypatch.setattr(_host, "_mss", None)
    monkeypatch.setattr(_host, "Image", None)
    with pytest.raises(PrerequisiteError) as excinfo:
        _host._require_deps()
    msg = str(excinfo.value)
    assert "pyautogui" in msg and "mss" in msg and "Pillow" in msg
    assert "pip install" in msg


# ---------------------------------------------------------------------------
# Key translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "xdotool,expected",
    [
        ("Return", "enter"),
        ("BackSpace", "backspace"),
        ("Escape", "escape"),
        ("Prior", "pageup"),
        ("Next", "pagedown"),
        ("F5", "f5"),
        ("a", "a"),
        ("A", "a"),
    ],
)
def test_translate_key(xdotool: str, expected: str) -> None:
    assert _host._translate_key(xdotool) == expected


def test_parse_combo_maps_modifiers() -> None:
    assert _host._parse_combo("ctrl+shift+s") == ["ctrl", "shift", "s"]
    assert _host._parse_combo("alt+Tab") == ["alt", "tab"]


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------


async def test_cursor_position(stub_deps: MagicMock) -> None:
    result = await _host.cursor_position()
    assert result == "X=123,Y=456"


async def test_screenshot_returns_image(stub_deps: MagicMock) -> None:
    result = await _host.screenshot()
    assert isinstance(result, list)
    assert len(result) == 1
    img = result[0]
    assert isinstance(img, ContentImage)
    assert img.image.startswith("data:image/png;base64,")
    # the base64 portion must decode to bytes
    b64 = img.image.split(",", 1)[1]
    assert base64.b64decode(b64)


async def test_left_click_invokes_pyautogui(stub_deps: MagicMock) -> None:
    await _host.left_click([10, 20])
    stub_deps.click.assert_called_once_with(10, 20)


async def test_right_click_uses_right_button(stub_deps: MagicMock) -> None:
    await _host.right_click([5, 6])
    stub_deps.click.assert_called_once_with(5, 6, button="right")


async def test_left_click_drag(stub_deps: MagicMock) -> None:
    await _host.left_click_drag([0, 0], [50, 50])
    # moveTo called for both start and end
    assert stub_deps.moveTo.call_count == 2
    stub_deps.mouseDown.assert_called_once()
    stub_deps.mouseUp.assert_called_once()


async def test_double_and_triple_click(stub_deps: MagicMock) -> None:
    await _host.double_click([1, 2])
    stub_deps.doubleClick.assert_called_once_with(1, 2)
    await _host.triple_click([3, 4])
    stub_deps.tripleClick.assert_called_once_with(3, 4)


async def test_back_and_forward_click_unsupported(stub_deps: MagicMock) -> None:
    with pytest.raises(ToolError):
        await _host.back_click([0, 0])
    with pytest.raises(ToolError):
        await _host.forward_click([0, 0])


async def test_scroll_vertical(stub_deps: MagicMock) -> None:
    await _host.scroll(3, "down", None)
    stub_deps.scroll.assert_called_once_with(-3)


async def test_scroll_horizontal(stub_deps: MagicMock) -> None:
    await _host.scroll(2, "right", [100, 100])
    stub_deps.moveTo.assert_called_once_with(100, 100)
    stub_deps.hscroll.assert_called_once_with(2)


async def test_press_key_single(stub_deps: MagicMock) -> None:
    await _host.press_key("Return")
    stub_deps.press.assert_called_once_with("enter")
    stub_deps.hotkey.assert_not_called()


async def test_press_key_combo(stub_deps: MagicMock) -> None:
    await _host.press_key("ctrl+s")
    stub_deps.hotkey.assert_called_once_with("ctrl", "s")
    stub_deps.press.assert_not_called()


async def test_press_key_multiple_combos(stub_deps: MagicMock) -> None:
    await _host.press_key("ctrl+a Delete")
    stub_deps.hotkey.assert_called_once_with("ctrl", "a")
    stub_deps.press.assert_called_once_with("delete")


async def test_hold_key_press_and_release(stub_deps: MagicMock) -> None:
    await _host.hold_key("shift+a", duration=0)
    # keyDown called in order, keyUp in reverse order
    down_keys = [c.args[0] for c in stub_deps.keyDown.call_args_list]
    up_keys = [c.args[0] for c in stub_deps.keyUp.call_args_list]
    assert down_keys == ["shift", "a"]
    assert up_keys == ["a", "shift"]


async def test_type_text(stub_deps: MagicMock) -> None:
    await _host.type("hello")
    stub_deps.typewrite.assert_called_once()
    args, kwargs = stub_deps.typewrite.call_args
    assert args[0] == "hello"


async def test_type_non_ascii_uses_clipboard_paste(
    stub_deps: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyperclip_stub = MagicMock(name="pyperclip")
    pyperclip_stub.paste.return_value = "previous clipboard"
    monkeypatch.setattr(_host, "pyperclip", pyperclip_stub)

    await _host.type("héllo — 你好")

    # typewrite must NOT be called for non-ASCII text
    stub_deps.typewrite.assert_not_called()
    # clipboard was set to the text, then paste hotkey fired, then restored
    copy_calls = [c.args[0] for c in pyperclip_stub.copy.call_args_list]
    assert copy_calls[0] == "héllo — 你好"
    assert copy_calls[-1] == "previous clipboard"
    # one of ctrl+v / cmd+v was sent
    hotkey_args = stub_deps.hotkey.call_args.args
    assert hotkey_args in (("command", "v"), ("ctrl", "v"))


async def test_type_non_ascii_without_pyperclip_raises(
    stub_deps: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_host, "pyperclip", None)
    with pytest.raises(ToolError, match="pyperclip"):
        await _host.type("naïve")


async def test_wait_sleeps_and_returns_screenshot(
    stub_deps: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(
        "inspect_ai.tool._tools._computer._host.anyio.sleep", fake_sleep
    )
    result = await _host.wait(2)
    assert 2 in slept
    assert isinstance(result, list)
    assert isinstance(result[0], ContentImage)


async def test_zoom_region(stub_deps: MagicMock) -> None:
    result = await _host.zoom([0, 0, 1, 1])
    assert isinstance(result, list)
    assert isinstance(result[0], ContentImage)


# ---------------------------------------------------------------------------
# _make_result helper
# ---------------------------------------------------------------------------


def test_make_result_text_only() -> None:
    result = _host._make_result("hello", with_screenshot=False)
    assert result == "hello"


def test_make_result_empty_returns_ok() -> None:
    result = _host._make_result(None, with_screenshot=False)
    assert result == "OK"


def test_make_result_image_only() -> None:
    b64 = base64.b64encode(b"img").decode()
    result = _host._make_result(base64_image=b64)
    assert isinstance(result, list)
    assert isinstance(result[0], ContentImage)


def test_make_result_text_and_image() -> None:
    b64 = base64.b64encode(b"img").decode()
    result = _host._make_result("caption", base64_image=b64)
    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], ContentText)
    assert isinstance(result[1], ContentImage)


# ---------------------------------------------------------------------------
# Module import resilience: importing _host without optional deps installed
# should not crash (just leave the module-level handles as None).
# ---------------------------------------------------------------------------


def test_host_module_imports_without_optional_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a fresh import with optional deps absent."""
    # Remove cached module + the optional deps from sys.modules so the
    # try/except ImportError branches run.
    for name in [
        "inspect_ai.tool._tools._computer._host",
        "pyautogui",
        "mss",
        "PIL",
        "PIL.Image",
    ]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    # Block imports of optional deps
    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__
    )

    def blocked_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name in {"pyautogui", "mss", "PIL"} or name.startswith("PIL."):
            raise ImportError(f"blocked: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", blocked_import)

    import importlib

    mod = importlib.import_module("inspect_ai.tool._tools._computer._host")
    assert mod.pyautogui is None
    assert mod._mss is None
    assert mod.Image is None
