from ._display import Display
from .rich import rich_display


def display() -> Display:
    return rich_display()
