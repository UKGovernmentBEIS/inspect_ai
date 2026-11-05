"""Utility to run commands asynchronously with a timeout."""

# TODO: Cloned from computer tool temporarily. Should resolve when we have a unified container package.

import asyncio
import os
import shlex

TRUNCATED_MESSAGE: str = "<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with `grep -n` in order to find the line numbers of what you are looking for.</NOTE>"
MAX_RESPONSE_LEN: int = 16000

# Utilities are resolved from the base system directories, never the image PATH:
# a PATH entry the sandbox user can write to would otherwise let an agent-planted
# `find` run with the tool's privileges (which may be root).
SYSTEM_PATH: str = "/usr/sbin:/usr/bin:/sbin:/bin"


def maybe_truncate(content: str, truncate_after: int | None = MAX_RESPONSE_LEN) -> str:
    """Truncate content and append a notice if content exceeds the specified length."""
    return (
        content
        if not truncate_after or len(content) <= truncate_after
        else content[:truncate_after] + TRUNCATED_MESSAGE
    )


async def run(
    cmd: list[str],
    timeout: float | None = 120.0,  # seconds
    truncate_after: int | None = MAX_RESPONSE_LEN,
) -> tuple[int, str, str]:
    """Run a command without a shell, asynchronously with a timeout.

    The program is looked up on `SYSTEM_PATH` rather than the inherited PATH.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PATH": SYSTEM_PATH},
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return (
            process.returncode or 0,
            maybe_truncate(stdout.decode(), truncate_after=truncate_after),
            maybe_truncate(stderr.decode(), truncate_after=truncate_after),
        )
    except (TimeoutError, asyncio.TimeoutError) as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise TimeoutError(
            f"Command {shlex.join(cmd)} timed out after {timeout} seconds"
        ) from exc
