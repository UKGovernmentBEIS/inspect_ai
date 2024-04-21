import contextlib
import os
from typing import Any, Generator

from dotenv import dotenv_values, find_dotenv, load_dotenv

from .platform import is_running_in_vscode


def init_dotenv(override: bool = is_running_in_vscode()) -> None:
    # if we are running in vscode, the vscode python extension is already reading in the
    # .env file. This means that editing the .env file within a given session does not
    # actually work! (since load_dotenv doesn't overwrite existing vars by default).
    # so, in this case we actually specify override so we get the more intuitive behavior
    load_dotenv(find_dotenv(usecwd=True), override=override)


@contextlib.contextmanager
def dotenv_environ(
    override: bool = is_running_in_vscode(),
) -> Generator[Any, Any, None]:
    # determine values to update
    update: dict[str, str] = {}
    values = dotenv_values(".env")
    for key, value in values.items():
        if value is not None and (override or (key not in os.environ.keys())):
            update[key] = value

    # vars to restore and remove on exit
    stomped = set(update.keys()) & set(os.environ.keys())
    update_after = {k: os.environ[k] for k in stomped}
    remove_after = frozenset(k for k in update if k not in os.environ)

    # do the thing
    try:
        os.environ.update(update)
        yield
    finally:
        os.environ.update(update_after)
        [os.environ.pop(k) for k in remove_after]
