import contextlib
import os
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse

from dotenv import dotenv_values, find_dotenv, load_dotenv

from .platform import is_running_in_vscode

INSPECT_LOG_DIR_VAR = "INSPECT_LOG_DIR"


def init_dotenv() -> None:

    # if we are running in vscode, the vscode python extension is already reading in the
    # .env file. This means that editing the .env file within a given session does not
    # actually work! (since load_dotenv doesn't overwrite existing vars by default).
    # so, in this case we actually specify override so we get the more intuitive behavior
    override = is_running_in_vscode()

    # look up the directory tree for a .env file
    dotenv_file = find_dotenv(usecwd=True)

    # we found one, process it
    if dotenv_file:

        # is there an INSPECT_LOG_DIR currently in the environment? (we will give it preference)
        environment_log_dir = os.environ.get(INSPECT_LOG_DIR_VAR, None)
        if environment_log_dir:
            # check for a relative dir, if we find one then resolve to absolute
            fs_scheme = urlparse(environment_log_dir).scheme
            if not fs_scheme and not os.path.isabs(environment_log_dir):
                environment_log_dir = Path(environment_log_dir).resolve().as_posix()

        # is there an INSPECT_LOG_DIR in the .env? If so resolve path relative to .env
        dotenv_log_dir = dotenv_values(dotenv_file).get(INSPECT_LOG_DIR_VAR, None)
        if dotenv_log_dir:
            # check for a relative dir, if we find one then resolve to absolute
            fs_scheme = urlparse(dotenv_log_dir).scheme
            if not fs_scheme and not os.path.isabs(dotenv_log_dir):
                dotenv_log_dir = (
                    (Path(dotenv_file).parent / dotenv_log_dir).resolve().as_posix()
                )

        # do the load, overriding as necessary if we are in vscode
        load_dotenv(dotenv_file, override=override)

        # apply the log_dir, giving preference to the existing environment var
        if environment_log_dir:
            os.environ[INSPECT_LOG_DIR_VAR] = environment_log_dir
        elif dotenv_log_dir:
            os.environ[INSPECT_LOG_DIR_VAR] = dotenv_log_dir


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
