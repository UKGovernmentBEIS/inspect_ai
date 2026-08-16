import sys
import types

from scale_factor import get_screen_scale_factor


def _install_fake_appkit(monkeypatch, screen: object) -> None:
    """Put a fake ``AppKit`` on ``sys.modules`` whose ``mainScreen()`` returns ``screen``."""
    module = types.ModuleType("AppKit")
    module.NSScreen = types.SimpleNamespace(mainScreen=lambda: screen)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "AppKit", module)


def test_darwin_returns_backing_scale_factor(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(
        monkeypatch, types.SimpleNamespace(backingScaleFactor=lambda: 2.0)
    )
    assert get_screen_scale_factor() == 2.0


def test_darwin_headless_screen_falls_back_to_one(monkeypatch):
    # NSScreen.mainScreen() is None when no display is attached (headless / over SSH);
    # dereferencing it used to raise AttributeError instead of defaulting to 1.0.
    monkeypatch.setattr(sys, "platform", "darwin")
    _install_fake_appkit(monkeypatch, None)
    assert get_screen_scale_factor() == 1.0


def test_darwin_missing_appkit_falls_back_to_one(monkeypatch):
    # pyobjc-framework-AppKit is an optional dependency; a missing import used to crash
    # the probe instead of degrading like the Windows and Linux branches do.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(
        sys.modules, "AppKit", None
    )  # `from AppKit import ...` -> ImportError
    assert get_screen_scale_factor() == 1.0
