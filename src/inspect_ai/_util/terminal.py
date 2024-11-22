import functools
import re
import select
import sys
from dataclasses import dataclass
from logging import getLogger
from typing import Any

logger = getLogger(__name__)


@dataclass
class RGB:
    r: int
    g: int
    b: int


@dataclass
class TerminalBackground:
    color: RGB
    brightness: float
    dark: bool


@functools.cache
def detect_terminal_background(
    default_color: RGB = RGB(0, 0, 0),
) -> TerminalBackground:
    """Query the terminal background color using OSC escape sequence.

    Based on https://dystroy.org/blog/terminal-light/#detect-whether-the-terminal-is-dark-or-light
    and https://github.com/Canop/terminal-light/blob/main/src/xterm.rs

    The `default_color` parameter ensures that you always get back a color
    even if when on windows or if an error occurs while querying the terminal
    (dark terminal is detected in this case).

    Args:
        default_color (Rgb): Default color in the case that we
          are unable to successfully query for colors.

    Returns:
        TerminalBackground: Terminal background color, brightness, and type.
    """

    def background_from_color(color: RGB) -> TerminalBackground:
        # compute brightness
        brightness = (color.r * 299 + color.g * 587 + color.b * 114) / 1000

        # return background
        return TerminalBackground(
            color=color, brightness=brightness, dark=brightness <= 128
        )

    # this does not work on windows so in that case we return the default
    if sys.platform == "win32":
        return background_from_color(default_color)

    try:
        # Send OSC 11 query for background color
        response = _query("\x1b]11;?\x07", 500)

        # Parse the response
        # Expected format: ]11;rgb:RRRR/GGGG/BBBB
        match = re.search(
            r"]11;rgb:([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})",
            response,
        )
        if not match:
            raise RuntimeError(f"Unexpected OSC response format: {response}")

        # Extract RGB values (using first 2 digits of each component)
        r = int(match.group(1)[:2], 16)
        g = int(match.group(2)[:2], 16)
        b = int(match.group(3)[:2], 16)
        color = RGB(r, g, b)

        # return background
        return background_from_color(color)

    except Exception as e:
        logger.debug("Error attempting to query terminal background color: " + str(e))
        return background_from_color(default_color)


if sys.platform != "win32":
    import termios
    import tty

    def _query(query_str: str, timeout_ms: int) -> str:
        """Send a query to the terminal and wait for response"""
        old_settings = None

        try:
            switch_to_raw = not _is_raw_mode_enabled()
            if switch_to_raw:
                old_settings = _enable_raw_mode()

            # Send the query
            sys.stdout.write(query_str)
            sys.stdout.flush()

            # Wait for response
            readable, _, _ = select.select([sys.stdin], [], [], timeout_ms / 1000.0)
            if not readable:
                raise RuntimeError("Timeout waiting for terminal query response")

            # Read response
            response: str = ""
            while True:
                char = sys.stdin.read(1)
                response += char
                if char == "\\" or (len(response) > 1 and response[-2:] == "\x1b\\"):
                    break

            return response

        finally:
            if old_settings is not None:
                _disable_raw_mode(old_settings)

    def _is_raw_mode_enabled() -> bool:
        """Check if the terminal is in raw mode"""
        mode = termios.tcgetattr(sys.stdin.fileno())
        return not bool(mode[3] & termios.ICANON)

    def _enable_raw_mode() -> Any:
        """Enable raw mode for the terminal"""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        return old_settings

    def _disable_raw_mode(old_settings: Any) -> None:
        """Disable raw mode for the terminal"""
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
