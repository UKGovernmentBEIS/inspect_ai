"""Adapted from: https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/computer_use_demo/tools/edit.py"""

import os
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Literal

from inspect_tool_support._in_process_tools._text_editor._run import maybe_truncate, run
from inspect_tool_support._util.common_types import ToolException

DEFAULT_HISTORY_PATH = "/tmp/inspect_editor_history.pkl"
SNIPPET_LINES: int = 4

HistoryEntryType = str | Literal[-1]
HistoryType = dict[Path, list[HistoryEntryType]]


async def view(path_str: str, view_range: list[int] | None = None) -> str:
    path = _validated_path(path_str, "view")
    if path.is_dir():
        path_str = str(path).rstrip("/") + "/"

        _, stdout, stderr = await run(
            rf"find {path_str} -maxdepth 2 -not -path '*/\.*'"
        )

        if stderr:
            raise ToolException(
                f"Encountered error attempting to view {path}: '{stderr}'"
            )

        stdout = "\n".join(
            os.path.normpath(line) for line in stdout.strip().split("\n")
        )
        return f"Here are the files and directories up to 2 levels deep in {path}, excluding hidden items:\n{stdout}\n"

    file_content = _read_file(path)
    init_line = 1
    if view_range:
        if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range):
            raise ToolException(
                "Invalid `view_range`. It should be a list of two integers."
            )
        file_lines = file_content.split("\n")
        n_lines_file = len(file_lines)
        init_line, final_line = view_range
        if init_line < 1 or init_line > n_lines_file:
            raise ToolException(
                f"Invalid `view_range`: {view_range}. Its first element `{init_line}` should be within the range of lines of the file: {[1, n_lines_file]}"
            )
        if final_line > n_lines_file:
            # Final line was too big - just show to EOF
            final_line = -1
        if final_line != -1 and final_line < init_line:
            raise ToolException(
                f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be larger or equal than its first `{init_line}`"
            )

        if final_line == -1:
            file_content = "\n".join(file_lines[init_line - 1 :])
        else:
            file_content = "\n".join(file_lines[init_line - 1 : final_line])

    return _make_output(file_content, str(path), init_line=init_line)


async def create(path_str: str, file_text: str) -> str:
    path = _validated_path(path_str, "create")
    _write_file(path, file_text)
    _add_history_entry(path, -1)
    return f"File created successfully at: {path}"


async def str_replace(path_str: str, old_str: str, new_str: str | None = None) -> str:
    if not old_str:
        raise ToolException(
            "str_replace: The `old_str` parameter cannot be empty. Consider using the `insert` command instead."
        )
    path = _validated_path(path_str, "str_replace")
    # Read the file content
    file_content = _read_file(path).expandtabs()
    old_str = old_str.expandtabs()
    new_str = new_str.expandtabs() if new_str is not None else ""

    # Check if old_str is unique in the file
    occurrences = file_content.count(old_str)
    if occurrences == 0:
        raise ToolException(
            f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."
        )
    elif occurrences > 1:
        file_content_lines = file_content.split("\n")
        lines = [
            idx + 1 for idx, line in enumerate(file_content_lines) if old_str in line
        ]
        raise ToolException(
            f"No replacement was performed. Multiple occurrences of old_str `{old_str}` in lines {lines}. Please ensure it is unique"
        )

    # Replace old_str with new_str
    new_file_content = file_content.replace(old_str, new_str)

    # Write the new content to the file
    _write_file(path, new_file_content)

    # Save the content to history
    _add_history_entry(path, file_content)

    # Create a snippet of the edited section
    replacement_line = file_content.split(old_str)[0].count("\n")
    start_line = max(0, replacement_line - SNIPPET_LINES)
    end_line = replacement_line + SNIPPET_LINES + new_str.count("\n")
    snippet = "\n".join(new_file_content.split("\n")[start_line : end_line + 1])

    # Prepare the success message
    success_msg = f"The file {path} has been edited. "
    success_msg += _make_output(snippet, f"a snippet of {path}", start_line + 1)
    success_msg += "Review the changes and make sure they are as expected. Edit the file again if necessary."

    return success_msg


async def insert(path_str: str, insert_line: int, new_str: str) -> str:
    path = _validated_path(path_str, "insert")
    file_text = _read_file(path).expandtabs()
    new_str = new_str.expandtabs()
    file_text_lines = file_text.split("\n")
    n_lines_file = len(file_text_lines)

    if insert_line < 0 or insert_line > n_lines_file:
        raise ToolException(
            f"Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: {[0, n_lines_file]}"
        )

    new_str_lines = new_str.split("\n")
    new_file_text_lines = (
        file_text_lines[:insert_line] + new_str_lines + file_text_lines[insert_line:]
    )
    snippet_lines = (
        file_text_lines[max(0, insert_line - SNIPPET_LINES) : insert_line]
        + new_str_lines
        + file_text_lines[insert_line : insert_line + SNIPPET_LINES]
    )

    new_file_text = "\n".join(new_file_text_lines)
    snippet = "\n".join(snippet_lines)

    _write_file(path, new_file_text)
    _add_history_entry(path, file_text)

    success_msg = f"The file {path} has been edited. "
    success_msg += _make_output(
        snippet,
        "a snippet of the edited file",
        max(1, insert_line - SNIPPET_LINES + 1),
    )
    success_msg += "Review the changes and make sure they are as expected (correct indentation, no duplicate lines, etc). Edit the file again if necessary."
    return success_msg


async def undo_edit(path_str: str) -> str:
    path = _validated_path(path_str, "undo_edit")
    history = _load_history()
    if not history[path]:
        raise ToolException(f"No edit history found for {path}.")
    entry = history[path].pop()
    _save_history(history)

    match entry:
        case -1:
            path.unlink()
            return f"File deleted at: {path}"
        case old_text:
            _write_file(path, old_text)
            return f"Last edit to {path} undone successfully. {_make_output(old_text, str(path))}"


def _validated_path(path_str: str, command: str) -> Path:
    """Check that the path/command combination is valid."""
    path = Path(path_str)

    # Check if its an absolute path
    if not path.is_absolute():
        raise ToolException(
            f"The path {path} is not an absolute path, it should start with `/`. Maybe you meant {Path('') / path}?"
        )
    # Check if path exists
    if not path.exists() and command != "create":
        raise ToolException(
            f"The path {path} does not exist. Please provide a valid path."
        )
    if path.exists() and command == "create":
        raise ToolException(
            f"File already exists at: {path}. Cannot overwrite files using command `create`."
        )
    # Check if the path points to a directory
    if path.is_dir():
        if command != "view":
            raise ToolException(
                f"The path {path} is a directory and only the `view` command can be used on directories"
            )
    return path


def _read_file(path: Path) -> str:
    """Read the content of a file from a given path; raise a ToolError if an error occurs."""
    try:
        return path.read_text()
    except Exception as e:
        raise ToolException(f"Ran into {e} while trying to read {path}") from None


def _write_file(path: Path, file: str) -> None:
    """Write the content of a file to a given path; raise a ToolError if an error occurs."""
    try:
        path.write_text(file)
    except Exception as e:
        raise ToolException(f"Ran into {e} while trying to write to {path}") from None


def _make_output(
    file_content: str,
    file_descriptor: str,
    init_line: int = 1,
    expand_tabs: bool = True,
) -> str:
    """Generate output for the CLI based on the content of a file."""
    file_content = maybe_truncate(file_content)
    if expand_tabs:
        file_content = file_content.expandtabs()
    file_content = "\n".join(
        [
            f"{i + init_line:6}\t{line}"
            for i, line in enumerate(file_content.split("\n"))
        ]
    )
    return (
        f"Here's the result of running `cat -n` on {file_descriptor}:\n"
        + file_content
        + "\n"
    )


def _add_history_entry(path: Path, entry: HistoryEntryType) -> None:
    history = _load_history()
    history[path].append(entry)
    _save_history(history)


def _save_history(history: HistoryType, file_path: str = DEFAULT_HISTORY_PATH) -> None:
    try:
        with open(file_path, "wb") as f:
            pickle.dump(history, f)
    except Exception as e:
        raise ToolException(f"Failed to save history to {file_path}: {e}") from None


def _load_history(file_path: str = DEFAULT_HISTORY_PATH) -> HistoryType:
    try:
        with open(file_path, "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        return defaultdict(list)
    except Exception as e:
        raise ToolException(f"Failed to load history from {file_path}: {e}") from None
