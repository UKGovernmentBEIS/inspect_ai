from logging import getLogger

from textual.driver import Driver

logger = getLogger(__name__)


# force mouse support for textual -- this works around an issue where
# mouse events are disabled after a reload of the vs code ide, see:
#   https://github.com/Textualize/textual/issues/5380
# we try/catch since we aren't 100% sure there aren't cases where doing
# this won't raise and we'd rather not fail hard in in these case
def textual_enable_mouse_support(driver: Driver) -> None:
    enable_mouse_support = getattr(driver, "_enable_mouse_support", None)
    if enable_mouse_support:
        try:
            enable_mouse_support()
            # Re-enable SGR-Pixels format if it was previously enabled.
            # See #1943.
            enable_mouse_pixels = getattr(driver, "_enable_mouse_pixels", None)
            if enable_mouse_pixels and getattr(driver, "_mouse_pixels", False):
                enable_mouse_pixels()
        except Exception as ex:
            logger.warning(f"Error enabling mouse support: {ex}")
