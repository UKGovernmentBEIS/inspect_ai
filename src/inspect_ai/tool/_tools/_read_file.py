from inspect_ai.util import sandbox as sandbox_env

from .._tool import Tool, ToolError, tool


@tool
def read_file(
    timeout: int | None = None,
    user: str | None = None,
    sandbox: str | None = None,
) -> Tool:
    """Read-only file reading tool.

    Read file contents from a sandbox environment with optional
    pagination for large files.

    Args:
        timeout: Timeout (in seconds) for read operation.
        user: User to execute as.
        sandbox: Optional sandbox environment name.
    """

    async def execute(
        file_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> str:
        """Read the contents of a file.

        Returns the file contents with line numbers prepended. Use
        offset and limit for pagination of large files.

        Args:
            file_path: Path to the file to read.
            offset: Line number to start reading from (0-indexed).
            limit: Maximum number of lines to read. Reads to end
                of file if not specified.
        """
        try:
            content = await sandbox_env(sandbox).read_file(file_path, text=True)
        except FileNotFoundError:
            raise ToolError(f"File not found: {file_path}")
        except PermissionError:
            raise ToolError(f"Permission denied: {file_path}")
        except IsADirectoryError:
            raise ToolError(f"Path is a directory, not a file: {file_path}")

        lines = content.splitlines()

        start = max(0, offset)
        end = (start + limit) if limit is not None else len(lines)
        end = min(len(lines), end)
        selected = lines[start:end]

        width = len(str(end))
        numbered = [
            f"{start + i + 1:>{width}}\t{line}" for i, line in enumerate(selected)
        ]
        return "\n".join(numbered)

    return execute
