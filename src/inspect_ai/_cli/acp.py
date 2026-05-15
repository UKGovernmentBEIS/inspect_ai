"""``inspect acp`` subcommand.

Phase 13 ships the ``--stdio`` mode — a transparent stdio↔socket
bridge that lets editors (Zed etc.) spawn ``inspect acp --stdio`` as
a subprocess and talk newline-delimited JSON-RPC to a running eval's
ACP server. Phase 15 will lift the bare-command error and add the
Inspect-native Textual TUI client.

The entry point uses ``asyncio.run`` (not ``anyio.run``) because
``acp.stdio.stdio_streams()`` requires an asyncio event loop —
``loop.connect_read_pipe`` / ``loop.connect_write_pipe`` are
asyncio-specific. The CLI is a leaf at the ACP transport boundary;
the asyncio anchor is intentional and matches the ``_stdio.py``
bridge it spawns.
"""

from __future__ import annotations

import asyncio
import sys

import click
from acp.stdio import stdio_streams

from inspect_ai.agent._acp._discovery import (
    DiscoveredEval,
    TargetAddress,
    TargetResolutionError,
    resolve_target,
)
from inspect_ai.agent._acp._stdio import bridge_stdio


@click.group(name="acp", invoke_without_command=True)
@click.option(
    "--stdio",
    is_flag=True,
    default=False,
    help="Run as a stdio↔socket bridge for editor clients (Zed etc.).",
)
@click.option(
    "--eval-id",
    default=None,
    help=(
        "Specific eval to attach to. Optional — when omitted with multiple "
        "evals running, the most-recently-started one is used (logged to "
        "stderr)."
    ),
)
@click.option(
    "--socket",
    "socket",
    default=None,
    help=(
        "Direct socket address (UNIX path or host:port) bypassing discovery. "
        "Optional — auto-discovery works in the common case."
    ),
)
@click.pass_context
def acp_command(
    ctx: click.Context,
    stdio: bool,
    eval_id: str | None,
    socket: str | None,
) -> None:
    """Connect to a running Inspect eval over the Agent Client Protocol."""
    if not stdio:
        click.echo(
            "Inspect's interactive ACP TUI client is not yet implemented "
            "(planned for Phase 15). For now, run `inspect acp --stdio` to "
            "use the editor bridge mode.",
            err=True,
        )
        ctx.exit(2)

    if eval_id is not None and socket is not None:
        click.echo(
            "--eval-id and --socket are mutually exclusive. --eval-id picks "
            "from the discovery directory; --socket bypasses discovery with "
            "a literal address. Pick one.",
            err=True,
        )
        ctx.exit(2)

    try:
        asyncio.run(_run_stdio_bridge(eval_id=eval_id, socket=socket))
    except KeyboardInterrupt:
        # Clean Ctrl-C exit; suppress the traceback that asyncio.run
        # would otherwise unwind.
        ctx.exit(0)


async def _run_stdio_bridge(
    *,
    eval_id: str | None,
    socket: str | None,
) -> None:
    """Resolve the target, open stdio streams, run the bridge.

    Failures land in stderr + non-zero exit codes. Editors that
    capture subprocess stderr will surface the diagnostic in a debug
    pane; users running the bridge by hand see it directly.
    """
    try:
        target, picked_from = resolve_target(eval_id=eval_id, socket=socket)
    except TargetResolutionError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(2)

    if picked_from is not None:
        _log_pick_notice(target, picked_from)

    try:
        in_stream, out_stream = await stdio_streams()
    except Exception as exc:  # pragma: no cover — stdio setup very rarely fails
        print(f"failed to open stdio streams: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)

    try:
        await bridge_stdio(in_stream, out_stream, target)
    except (ConnectionRefusedError, FileNotFoundError) as exc:
        # Server socket exists in the discovery file but no live server
        # is listening at it (crashed mid-flight, between unlink and
        # bind, etc.). Surface a clean message instead of a traceback.
        print(
            f"could not connect to eval ACP server at {target.describe()}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)


def _log_pick_notice(
    target: TargetAddress,
    picked_from: list[DiscoveredEval],
) -> None:
    """Stderr notice when discovery had multiple alive evals to choose from.

    Editors typically surface subprocess stderr in a debug pane, so
    the user gets a clear "here's why this eval was picked" trail
    without having to inspect logs.
    """
    others = [e for e in picked_from if e.eval_id != target.eval_id]
    candidate_list = ", ".join(
        f"{e.eval_id} (started {e.started_at:.0f})" for e in picked_from
    )
    print(
        f"inspect acp: attached to {target.eval_id} (most recent of "
        f"{len(picked_from)} evals; use --eval-id to pick a different one). "
        f"Candidates: {candidate_list}. Ignored: "
        f"{', '.join(e.eval_id for e in others) or 'none'}.",
        file=sys.stderr,
        flush=True,
    )
