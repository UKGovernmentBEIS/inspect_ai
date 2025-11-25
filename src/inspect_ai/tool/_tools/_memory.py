"""Memory tool for managing persistent information in /memories directory."""

from pathlib import Path
from typing import Literal

from pydantic import Field

from inspect_ai.tool import Tool, ToolError, tool
from inspect_ai.util import StoreModel, store_as
from inspect_ai.util._resource import resource

SNIPPET_LINES: int = 4


class MemoryStore(StoreModel):
    seeding_complete: bool = Field(default=False)
    files: dict[str, str] = Field(default_factory=dict)
    dirs: list[str] = Field(default_factory=list)


@tool
def memory(*, initial_data: dict[str, str] | None = None) -> Tool:
    """Memory tool for managing persistent information.

    The description for the memory tool is based on the documentation for the Claude
    [system prompt](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool#prompting-guidance) associated with the use of the memory tool.

    Args:
        initial_data: Optional dict mapping file paths to content for pre-seeding
            the memory store. Keys should be valid /memories paths (e.g.,
            "/memories/file.txt"). Values are resolved via resource(), supporting
            inline strings, file paths, or remote resources (s3://, https://).
            Seeding happens once on first tool execution.

    Returns:
        Memory tool for file operations in /memories directory.
    """

    async def execute(
        command: Literal["view", "create", "str_replace", "insert", "delete", "rename"],
        path: str | None = None,
        file_text: str | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
        insert_text: str | None = None,
        view_range: list[int] | None = None,
        old_path: str | None = None,
        new_path: str | None = None,
    ) -> str:
        """Memory tool for managing persistent information.

        IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE.

        MEMORY PROTOCOL:
        1. Use the `view` command of your `memory` tool to check for earlier progress.
        2. ... (work on the task) ...
            - As you make progress, record status / progress / thoughts etc in your memory.
        ASSUME INTERRUPTION: Your context window might be reset at any moment, so you risk losing any progress that is not recorded in your memory directory.

        Note: when editing your memory folder, always try to keep its content up-to-date, coherent and organized. You can rename or delete files that are no longer relevant. Do not create new files unless necessary.

        Args:
            command: Command to execute (view, create, str_replace, insert, delete,
                rename)
            path: Required parameter for `view`, `create`, `str_replace`, `insert`,
                and `delete` commands. Path to file or directory in /memories, e.g.
                `/memories/file.txt` or `/memories/dir`.
            file_text: Required parameter for `create` command, with the content
                of the file to be created.
            old_str: Required parameter for `str_replace` command containing the
                string in `path` to replace.
            new_str: Optional parameter for `str_replace` command containing the
                new string (if not given, the string will be deleted).
            insert_line: Required parameter for `insert` command. The `insert_text`
                will be inserted AFTER the line `insert_line` of `path`.
            insert_text: Required parameter for `insert` command containing the
                text to insert.
            view_range: Optional parameter for `view` command when `path` points
                to a file. If none is given, the full file is shown. If provided,
                the file will be shown in the indicated line number range, e.g. [11, 12]
                will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]`
                shows all lines from `start_line` to the end of the file.
            old_path: Required parameter for `rename` command containing the current
                path.
            new_path: Required parameter for `rename` command containing the target
                path.

        Returns:
            Result message string
        """
        store = store_as(MemoryStore)
        if not store.seeding_complete:
            if initial_data:
                for seed_path, value in initial_data.items():
                    _create(store, seed_path, resource(value))
            store.seeding_complete = True

        match command:
            case "view":
                return _view(store, path, view_range)
            case "create":
                return _create(store, path, file_text)
            case "str_replace":
                return _str_replace(store, path, old_str, new_str)
            case "insert":
                return _insert(store, path, insert_line, insert_text)
            case "delete":
                return _delete(store, path)
            case "rename":
                return _rename(store, old_path, new_path)
            case _:
                raise ToolError(f"Unknown command: {command}")

    return execute


def _validate_path(path: str) -> str:
    """Validate path starts with /memories and has no traversal."""
    if not path:
        raise ToolError("Path cannot be empty")

    # Normalize separators
    path = path.replace("\\", "/")

    # Must start with /memories
    if not path.startswith("/memories"):
        raise ToolError(
            f"Invalid path: all paths must start with /memories, got {path}"
        )

    try:
        # Convert to pathlib Path and resolve (eliminates .., symlinks, etc)
        resolved = Path(path).resolve()
        base = Path("/memories").resolve()

        # Verify resolved path is within /memories
        resolved.relative_to(base)
    except ValueError:
        raise ToolError(f"Invalid path: {path} resolves outside /memories directory")

    # Remove trailing slash except for /memories itself
    if path != "/memories" and path.endswith("/"):
        path = path.rstrip("/")

    return path


def _path_exists(store: MemoryStore, path: str) -> bool:
    return path in store.files or path in store.dirs


def _is_dir(store: MemoryStore, path: str) -> bool:
    return path in store.dirs


def _read_file(store: MemoryStore, path: str) -> str:
    if path not in store.files:
        raise ToolError(f"File not found: {path}")
    return store.files[path]


def _write_file(store: MemoryStore, path: str, content: str) -> None:
    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Create parent directories
    parts = path.rsplit("/", 1)
    if len(parts) == 2:
        parent = parts[0]
        if parent and parent != "/memories":
            _ensure_parent_dirs(store, parent)

    store.files[path] = content


def _ensure_parent_dirs(store: MemoryStore, path: str) -> None:
    # Build all parent paths
    parts = path.split("/")
    current = ""
    for part in parts:
        if not part:
            continue
        if current:
            current += "/" + part
        else:
            current = "/" + part
        if current not in store.dirs:
            store.dirs.append(current)


def _list_directory(store: MemoryStore, path: str, max_depth: int = 2) -> list[str]:
    results = []

    # Normalize path for comparison
    prefix = path if path == "/memories" else path + "/"
    base_depth = path.count("/")

    # Add directories
    for dir_path in sorted(store.dirs):
        if dir_path.startswith(prefix) and dir_path != path:
            depth = dir_path.count("/") - base_depth
            if depth <= max_depth:
                results.append(dir_path)

    # Add files
    for file_path in sorted(store.files.keys()):
        if file_path.startswith(prefix):
            depth = file_path.count("/") - base_depth
            if depth <= max_depth:
                results.append(file_path)

    return results


def _make_output(file_content: str, file_descriptor: str, init_line: int = 1) -> str:
    lines = file_content.split("\n")
    numbered_lines = [f"{i + init_line:6}\t{line}" for i, line in enumerate(lines)]
    content = "\n".join(numbered_lines)
    return f"Here's the result of running `cat -n` on {file_descriptor}:\n{content}\n"


def _view(
    store: MemoryStore, path: str | None, view_range: list[int] | None = None
) -> str:
    if not path:
        raise ToolError("Path is required for view command")

    path = _validate_path(path)

    if not _path_exists(store, path):
        raise ToolError(f"The path {path} does not exist. Please provide a valid path.")

    if _is_dir(store, path):
        # List directory contents
        contents = _list_directory(store, path)
        if not contents:
            return f"Directory {path} is empty.\n"
        contents_str = "\n".join(contents)
        return f"Here are the files and directories up to 2 levels deep in {path}, excluding hidden items:\n{contents_str}\n"

    # Read file
    file_content = _read_file(store, path)
    init_line = 1

    if view_range:
        if len(view_range) != 2 or not all(isinstance(i, int) for i in view_range):
            raise ToolError(
                "Invalid `view_range`. It should be a list of two integers."
            )

        file_lines = file_content.split("\n")
        n_lines_file = len(file_lines)
        init_line, final_line = view_range

        if init_line < 1 or init_line > n_lines_file:
            raise ToolError(
                f"Invalid `view_range`: {view_range}. Its first element `{init_line}` should be within the range of lines of the file: {[1, n_lines_file]}"
            )

        if final_line > n_lines_file:
            final_line = -1

        if final_line != -1 and final_line < init_line:
            raise ToolError(
                f"Invalid `view_range`: {view_range}. Its second element `{final_line}` should be larger or equal than its first `{init_line}`"
            )

        if final_line == -1:
            file_content = "\n".join(file_lines[init_line - 1 :])
        else:
            file_content = "\n".join(file_lines[init_line - 1 : final_line])

    return _make_output(file_content, str(path), init_line=init_line)


def _create(store: MemoryStore, path: str | None, file_text: str | None) -> str:
    if not path:
        raise ToolError("Path is required for create command")
    if file_text is None:
        raise ToolError("file_text is required for create command")

    path = _validate_path(path)

    # Unlike text_editor, memory tool allows overwriting
    _write_file(store, path, file_text)
    return f"File created successfully at: {path}"


def _str_replace(
    store: MemoryStore, path: str | None, old_str: str | None, new_str: str | None
) -> str:
    if not path:
        raise ToolError("Path is required for str_replace command")
    if not old_str:
        raise ToolError(
            "str_replace: The `old_str` parameter cannot be empty. Consider using the `insert` command instead."
        )

    path = _validate_path(path)

    if not _path_exists(store, path):
        raise ToolError(f"The path {path} does not exist. Please provide a valid path.")

    if _is_dir(store, path):
        raise ToolError(
            f"The path {path} is a directory and only the `view` command can be used on directories"
        )

    # Read file content
    file_content = _read_file(store, path).expandtabs()
    old_str = old_str.expandtabs()
    new_str = new_str.expandtabs() if new_str is not None else ""

    # Check if old_str is unique
    occurrences = file_content.count(old_str)
    if occurrences == 0:
        raise ToolError(
            f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."
        )
    elif occurrences > 1:
        file_content_lines = file_content.split("\n")
        lines = [
            idx + 1 for idx, line in enumerate(file_content_lines) if old_str in line
        ]
        raise ToolError(
            f"No replacement was performed. Multiple occurrences of old_str `{old_str}` in lines {lines}. Please ensure it is unique"
        )

    # Replace
    new_file_content = file_content.replace(old_str, new_str)
    _write_file(store, path, new_file_content)

    # Create snippet
    replacement_line = file_content.split(old_str)[0].count("\n")
    start_line = max(0, replacement_line - SNIPPET_LINES)
    end_line = replacement_line + SNIPPET_LINES + new_str.count("\n")
    snippet = "\n".join(new_file_content.split("\n")[start_line : end_line + 1])

    success_msg = f"The file {path} has been edited. "
    success_msg += _make_output(snippet, f"a snippet of {path}", start_line + 1)
    success_msg += "Review the changes and make sure they are as expected. Edit the file again if necessary."

    return success_msg


def _insert(
    store: MemoryStore,
    path: str | None,
    insert_line: int | None,
    insert_text: str | None,
) -> str:
    """Insert text at line number."""
    if not path:
        raise ToolError("Path is required for insert command")
    if insert_line is None:
        raise ToolError("insert_line is required for insert command")
    if insert_text is None:
        raise ToolError("insert_text is required for insert command")

    path = _validate_path(path)

    if not _path_exists(store, path):
        raise ToolError(f"The path {path} does not exist. Please provide a valid path.")

    if _is_dir(store, path):
        raise ToolError(
            f"The path {path} is a directory and only the `view` command can be used on directories"
        )

    file_text = _read_file(store, path).expandtabs()
    insert_text = insert_text.expandtabs()
    file_text_lines = file_text.split("\n")
    n_lines_file = len(file_text_lines)

    if insert_line < 0 or insert_line > n_lines_file:
        raise ToolError(
            f"Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: {[0, n_lines_file]}"
        )

    insert_text_lines = insert_text.split("\n")
    new_file_text_lines = (
        file_text_lines[:insert_line]
        + insert_text_lines
        + file_text_lines[insert_line:]
    )
    snippet_lines = (
        file_text_lines[max(0, insert_line - SNIPPET_LINES) : insert_line]
        + insert_text_lines
        + file_text_lines[insert_line : insert_line + SNIPPET_LINES]
    )

    new_file_text = "\n".join(new_file_text_lines)
    snippet = "\n".join(snippet_lines)

    _write_file(store, path, new_file_text)

    success_msg = f"The file {path} has been edited. "
    success_msg += _make_output(
        snippet,
        "a snippet of the edited file",
        max(1, insert_line - SNIPPET_LINES + 1),
    )
    success_msg += "Review the changes and make sure they are as expected (correct indentation, no duplicate lines, etc). Edit the file again if necessary."

    return success_msg


def _delete(store: MemoryStore, path: str | None) -> str:
    if not path:
        raise ToolError("Path is required for delete command")

    path = _validate_path(path)

    if not _path_exists(store, path):
        raise ToolError(f"The path {path} does not exist. Please provide a valid path.")

    if _is_dir(store, path):
        # Delete directory and all contents
        prefix = path + "/"

        # Delete all files in directory
        files_to_delete = [f for f in store.files if f.startswith(prefix) or f == path]
        for f in files_to_delete:
            del store.files[f]

        # Delete all subdirectories
        dirs_to_delete = [d for d in store.dirs if d.startswith(prefix) or d == path]
        for d in dirs_to_delete:
            if d in store.dirs:
                store.dirs.remove(d)
    else:
        # Delete file
        del store.files[path]

    return f"Successfully deleted: {path}"


def _rename(store: MemoryStore, old_path: str | None, new_path: str | None) -> str:
    if not old_path:
        raise ToolError("old_path is required for rename command")
    if not new_path:
        raise ToolError("new_path is required for rename command")

    old_path = _validate_path(old_path)
    new_path = _validate_path(new_path)

    if not _path_exists(store, old_path):
        raise ToolError(
            f"The path {old_path} does not exist. Please provide a valid path."
        )

    if _is_dir(store, old_path):
        # Rename directory and all contents
        old_prefix = old_path + "/"

        # Rename all files in directory
        files_to_rename = {
            f: f.replace(old_path, new_path, 1)
            for f in store.files
            if f.startswith(old_prefix) or f == old_path
        }

        for old_f, new_f in files_to_rename.items():
            store.files[new_f] = store.files.pop(old_f)

        # Rename all subdirectories
        dirs_to_rename = {
            d: d.replace(old_path, new_path, 1)
            for d in store.dirs
            if d.startswith(old_prefix) or d == old_path
        }

        for old_d in dirs_to_rename:
            if old_d in store.dirs:
                store.dirs.remove(old_d)
        for new_d in dirs_to_rename.values():
            if new_d not in store.dirs:
                store.dirs.append(new_d)
    else:
        # Rename file
        store.files[new_path] = store.files.pop(old_path)

        # Ensure parent directories exist
        parts = new_path.rsplit("/", 1)
        if len(parts) == 2:
            parent = parts[0]
            if parent and parent != "/memories":
                _ensure_parent_dirs(store, parent)

    return f"Successfully renamed {old_path} to {new_path}"
