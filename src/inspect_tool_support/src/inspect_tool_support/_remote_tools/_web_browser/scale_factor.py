import subprocess
import sys

# Playwright launches Chromium with --force-device-scale-factor=1 by default, which
# ensures consistent rendering and measurement behavior using CSS pixels instead of
# native device pixels, regardless of the actual display's DPI. On HiDPI displays,
# like Apple Retina, the ratio of native pixels to CSS pixels is typically 2x or even 3x.
#
# However, the Chrome DevTools Protocol (CDP) has an inconsistency when running on
# HiDPI devices with --force-device-scale-factor=1. Although window.devicePixelRatio
# correctly reports as 1 (honoring the forced scale factor), CDP's LayoutTreeSnapshot.bounds
# still returns coordinates in native device pixels without applying the forced scale factor,
# resulting in a mismatch between CSS and native pixels.
#
# To work around this inconsistency, we determine the native scale factor independently
# of browser-reported values, using system-level data via the get_screen_scale_factor helper
# function. We then apply this actual scale factor to adjust the window bounds, ensuring
# they are in the same coordinate space as LayoutTreeSnapshot.bounds. This alignment
# allows the code to accurately calculate node visibility.


def get_screen_scale_factor() -> float:
    if sys.platform == "darwin":
        # `pip install pyobjc-framework-AppKit` is required to run headfully on macOS
        from AppKit import NSScreen  # type: ignore

        return NSScreen.mainScreen().backingScaleFactor()
    elif sys.platform == "win32":
        try:
            # Using GetDpiForSystem from Windows API
            import ctypes

            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            return user32.GetDpiForSystem() / 96.0
        except Exception:
            return 1.0
    elif sys.platform.startswith("linux"):
        try:
            # Try to get scaling from gsettings (GNOME)
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "scaling-factor"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())

            # Try to get scaling from xrandr (X11)
            result = subprocess.run(
                ["xrandr", "--current"], capture_output=True, text=True
            )
            if result.returncode == 0:
                # Parse xrandr output to find scaling
                # This is a simplified check - might need adjustment
                for line in result.stdout.splitlines():
                    if "connected primary" in line and "x" in line:
                        # Look for something like "3840x2160+0+0"
                        resolution = line.split()[3].split("+")[0]
                        if "3840x2160" in resolution:  # 4K
                            return 2.0
            return 1.0
        except Exception:
            return 1.0
    return 1.0  # Default fallback
