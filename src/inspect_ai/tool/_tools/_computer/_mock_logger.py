"""
This module is a temporary solution that allows one to alter the log level of a specific child logger.

As currently implemented, even there is no way to enable DEBUG level console logging for a child logger
without also enabling DEBUG level logging for the root logger.

This should be resolved, but in the meantime, this module provides a workaround.
"""

import logging


class MockLogger:
    level = logging.INFO

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        if self.level <= logging.DEBUG:
            print(f"DEBUG: {msg % args}")

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        if self.level <= logging.INFO:
            print(f"INFO: {msg % args}")

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        if self.level <= logging.WARNING:
            print(f"WARNING: {msg % args}")

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        if self.level <= logging.ERROR:
            print(f"ERROR: {msg % args}")

    def critical(self, msg: str, *args: object, **kwargs: object) -> None:
        if self.level <= logging.CRITICAL:
            print(f"CRITICAL: {msg % args}")

    def exception(self, msg: str, *args: object, **kwargs: object) -> None:
        print(f"EXCEPTION: {msg % args}")
        if "exc_info" in kwargs and kwargs["exc_info"]:
            import traceback

            traceback.print_exc()

    def setLevel(self, level: int) -> None:
        self.level = level
