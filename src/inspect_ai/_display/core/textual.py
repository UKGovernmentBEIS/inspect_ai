from logging import getLogger

from textual.driver import Driver

logger = getLogger(__name__)


# force mouse support for textual -- this works around an issue where
# mouse events are disabled after a reload of the vs code ide, see:
#   https://github.com/Textualize/textual/issues/5380
# ansi codes for enabling mouse support are idempotent so it is fine
# to do this even in cases where mouse support is already enabled.
# we try/catch since we aren't 100% sure there aren't cases where doing
# this won't raise and we'd rather not fail hard in in these case
def textual_enable_mouse_support(driver: Driver) -> None:
    enable_mouse_support = getattr(driver, "_enable_mouse_support", None)
    if enable_mouse_support:
        try:
            enable_mouse_support()
        except Exception as ex:
            logger.warning(f"Error enabling mouse support: {ex}")
