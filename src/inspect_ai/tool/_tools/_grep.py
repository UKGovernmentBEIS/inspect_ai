from typing import Literal

from inspect_ai.util import sandbox as sandbox_env

from .._tool import Tool, ToolError, tool


@tool
def grep(
    timeout: int | None = None,
    user: str | None = None,
    sandbox: str | None = None,
) -> Tool:
    """Read-only text search tool.

    Search for patterns in files within a sandbox environment.

    Args:
        timeout: Timeout (in seconds) for search.
        user: User to execute as.
        sandbox: Optional sandbox environment name.
    """

    async def execute(
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        fixed_strings: bool = False,
        output_mode: Literal["content", "files_with_matches", "count"] = "content",
    ) -> str:
        """Search for a pattern in files.

        Recursively searches for a pattern and returns results based
        on the output_mode setting.

        Args:
            pattern: Regular expression pattern to search for
                (or literal string if fixed_strings is True).
            path: File or directory to search (defaults to working
                directory).
            glob: Glob pattern to filter which files to search
                (e.g. "*.py").
            fixed_strings: If True, treat pattern as a literal string
                rather than a regular expression.
            output_mode: Output format. "content" returns matching
                lines with file paths and line numbers. "files_with_matches"
                returns only file paths containing matches. "count"
                returns match counts per file.
        """
        cmd = ["grep", "-rn"]
        if fixed_strings:
            cmd.append("-F")
        if glob:
            cmd.extend(["--include", glob])
        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        cmd.extend(["--", pattern, path])

        result = await sandbox_env(sandbox).exec(cmd=cmd, timeout=timeout, user=user)

        # exit code 1 means no matches (not an error)
        if result.returncode == 1:
            return "No matches found."

        if result.returncode != 0:
            raise ToolError(result.stderr.strip() if result.stderr else "grep failed")

        output = result.stdout.strip()

        # for count mode, filter out files with 0 matches
        if output_mode == "count":
            lines = [line for line in output.splitlines() if not line.endswith(":0")]
            return "\n".join(lines) if lines else "No matches found."

        return output

    return execute
