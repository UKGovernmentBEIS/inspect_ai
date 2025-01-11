import contextlib
import shelve
from shelve import Shelf
from typing import Iterator

from inspect_ai._util.appdirs import inspect_data_dir


@contextlib.contextmanager
def inspect_shelf(name: str) -> Iterator[Shelf[str]]:
    shelf_path = inspect_data_dir("shelves") / name
    with shelve.open(shelf_path) as shelf:
        yield shelf
