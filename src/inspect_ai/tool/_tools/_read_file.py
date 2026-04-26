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
        start = max(0, offset) + 1
        if limit is not None:
            end = start + limit - 1
            awk_prog = (
                f"NR >= {start} && NR <= {end} "
                f'{{ printf "%d\\t%s\\n", NR, $0 }} '
                f"NR > {end} {{ exit }}"
            )
        else:
            awk_prog = f'NR >= {start} {{ printf "%d\\t%s\\n", NR, $0 }}'

        # Pure argv — no shell interpolation of file_path.
        # Prefix with ./ if path starts with - to prevent awk option parsing.
        safe_path = f"./{file_path}" if file_path.startswith("-") else file_path
        result = await sandbox_env(sandbox).exec(
            cmd=["awk", awk_prog, safe_path],
            timeout=timeout,
            user=user,
        )

        if not result.success:
            stderr = result.stderr.strip().lower() if result.stderr else ""
            if "no such file" in stderr or "not found" in stderr:
                raise ToolError(f"File not found: {file_path}")
            elif "permission denied" in stderr:
                raise ToolError(f"Permission denied: {file_path}")
            elif "is a directory" in stderr:
                raise ToolError(f"Path is a directory, not a file: {file_path}")
            else:
                raise ToolError(
                    result.stderr.strip()
                    if result.stderr
                    else f"Error reading: {file_path}"
                )

        return result.stdout.rstrip("\n")

    return execute
