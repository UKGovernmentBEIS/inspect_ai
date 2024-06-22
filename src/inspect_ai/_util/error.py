import sys
from importlib.metadata import version
from types import TracebackType
from typing import Callable

from rich import print
from rich.console import RenderableType


def pip_dependency_error(feature: str, dependencies: list[str]) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} requires optional dependencies. "
        f"Install with:\n\n[bold]pip install {' '.join(dependencies)}[/bold]\n"
    )


def module_version_error(
    feature: str, package: str, required_version: str
) -> Exception:
    return PrerequisiteError(
        f"[bold]ERROR[/bold]: {feature} requires at least version {required_version} of package {package} "
        f"(you have version {version(package)} installed).\n\n"
        f"Upgrade with:\n\n[bold]pip install --upgrade {package}[/bold]\n"
    )


def exception_message(ex: BaseException) -> str:
    return getattr(ex, "message", repr(ex))


class PrerequisiteError(Exception):
    def __init__(self, message: RenderableType) -> None:
        self.message = message


def exception_hook() -> Callable[..., None]:
    sys_handler = sys.excepthook

    def handler(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: TracebackType,
    ) -> None:
        if isinstance(exception, PrerequisiteError):
            print("\n", exception.message, sep="")
        else:
            sys_handler(exception_type, exception, traceback)

    return handler
