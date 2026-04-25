from inspect_ai.util import sandbox as sandbox_env

from .._tool import Tool, ToolError, tool


@tool
def list_files(
    timeout: int | None = None,
    user: str | None = None,
    sandbox: str | None = None,
) -> Tool:
    """Read-only directory listing tool.

    List files and directories in a sandbox environment.

    Args:
        timeout: Timeout (in seconds) for listing.
        user: User to execute as.
        sandbox: Optional sandbox environment name.
    """

    async def execute(path: str = ".", depth: int | None = None) -> str:
        """List files and directories at the given path.

        Returns one path per line. Use depth to limit the recursion
        level: 1 lists only immediate contents, None lists everything
        recursively.

        Args:
            path: Directory path to list (defaults to working directory).
            depth: Maximum depth for recursive listing. 1 lists only the
                immediate directory. None lists all files recursively.
        """
        cmd = ["find", path]
        if depth is not None:
            cmd.extend(["-maxdepth", str(depth)])
        cmd.extend(["-not", "-name", ".", "-print"])

        result = await sandbox_env(sandbox).exec(cmd=cmd, timeout=timeout, user=user)

        if not result.success:
            raise ToolError(
                result.stderr.strip() if result.stderr else f"Error listing: {path}"
            )

        output = result.stdout.strip()
        if not output:
            return f"No files found in: {path}"

        lines = sorted(output.splitlines())
        return "\n".join(lines)

    return execute
