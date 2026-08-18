"""``inspect acp`` subcommand.

Two modes:

- ``--stdio`` runs a transparent stdio↔socket bridge for editors
  (Zed etc.) that spawn ``inspect acp --stdio`` as a subprocess and
  talk newline-delimited JSON-RPC to a running eval's ACP server.
- Without ``--stdio``, launches the Inspect-native Textual TUI
  client (Phase 15).

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

from inspect_ai.agent._acp.discovery import (
    DiscoveredEval,
    TargetAddress,
    TargetResolutionError,
    resolve_target,
)
from inspect_ai.agent._acp.stdio import TripleResolutionError, bridge_stdio


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
        "evals running, the TUI's picker lists them (or the bridge picks the "
        "most-recently-started, logged to stderr)."
    ),
)
@click.option(
    "--server",
    "server",
    default=None,
    help=(
        "Direct ACP server address (UNIX path or host:port) bypassing local "
        "discovery. Use to attach to a remote machine, or to override the "
        "auto-discovered address. Shared by --stdio and TUI modes."
    ),
)
@click.option(
    "--task-id",
    "task_id",
    default=None,
    help=(
        "Direct-attach filter: task name. In TUI mode the flags filter the "
        "picker (any combination); a unique match auto-attaches. In --stdio "
        "mode all three of --task-id / --sample-id / --epoch must be set "
        "together to uniquely identify one session for the bridge to attach to."
    ),
)
@click.option(
    "--sample-id",
    "sample_id",
    default=None,
    help="Direct-attach filter: sample id. See --task-id for combined semantics.",
)
@click.option(
    "--epoch",
    "epoch",
    type=int,
    default=None,
    help="Direct-attach filter: epoch (integer). See --task-id for combined semantics.",
)
@click.pass_context
def acp_command(
    ctx: click.Context,
    stdio: bool,
    eval_id: str | None,
    server: str | None,
    task_id: str | None,
    sample_id: str | None,
    epoch: int | None,
) -> None:
    """Connect to a running Inspect eval over the Agent Client Protocol."""
    if eval_id is not None and server is not None:
        click.echo(
            "--eval-id and --server are mutually exclusive. --eval-id picks "
            "from the discovery directory; --server bypasses discovery with "
            "a literal address. Pick one.",
            err=True,
        )
        ctx.exit(2)

    # In stdio mode the bridge needs a complete triple to do a deterministic
    # direct-attach — partial filters can't be conveyed to an editor that
    # only speaks standard ACP. TUI mode can show a filtered picker, so any
    # combination is allowed there.
    triple_provided = (task_id, sample_id, epoch)
    triple_count = sum(1 for v in triple_provided if v is not None)
    if stdio and 0 < triple_count < 3:
        missing = []
        if task_id is None:
            missing.append("--task-id")
        if sample_id is None:
            missing.append("--sample-id")
        if epoch is None:
            missing.append("--epoch")
        click.echo(
            "--stdio direct-attach requires all of --task-id, --sample-id, and "
            f"--epoch. Missing: {', '.join(missing)}. Omit all three to use the "
            "editor's session/new picker flow.",
            err=True,
        )
        ctx.exit(2)

    try:
        if stdio:
            asyncio.run(
                _run_stdio_bridge(
                    eval_id=eval_id,
                    server=server,
                    task_id=task_id,
                    sample_id=sample_id,
                    epoch=epoch,
                )
            )
        else:
            from inspect_ai.agent._acp.tui import run_tui

            asyncio.run(
                run_tui(
                    eval_id=eval_id,
                    server=server,
                    task_id=task_id,
                    sample_id=sample_id,
                    epoch=epoch,
                )
            )
    except KeyboardInterrupt:
        # Clean Ctrl-C exit; suppress the traceback that asyncio.run
        # would otherwise unwind.
        ctx.exit(0)


async def _run_stdio_bridge(
    *,
    eval_id: str | None,
    server: str | None,
    task_id: str | None,
    sample_id: str | None,
    epoch: int | None,
) -> None:
    """Resolve the target, open stdio streams, run the bridge.

    Failures land in stderr + non-zero exit codes. Editors that
    capture subprocess stderr will surface the diagnostic in a debug
    pane; users running the bridge by hand see it directly.

    When all three of ``task_id`` / ``sample_id`` / ``epoch`` are
    set (the mutex check in :func:`acp_command` enforces all-or-none
    in stdio mode), the bridge runs in rewrite mode: it preflights
    ``inspect/list_sessions`` to confirm the triple resolves to a
    live session, then translates the editor's first ``session/new``
    request into an ``inspect/attach`` so the editor's standard
    handshake transparently produces a direct bind without going
    through the in-channel picker.
    """
    try:
        target, picked_from = resolve_target(eval_id=eval_id, server=server)
    except TargetResolutionError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(2)

    if picked_from is not None:
        _log_pick_notice(target, picked_from)

    rewrite_target: str | None = None
    if task_id is not None and sample_id is not None and epoch is not None:
        triple = f"{task_id}/{sample_id}/{epoch}"
        try:
            from inspect_ai.agent._acp.stdio import preflight_resolve_triple

            await preflight_resolve_triple(target, triple)
        except TripleResolutionError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            sys.exit(2)
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            print(
                f"could not connect to eval ACP server at {target.describe()}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(2)
        rewrite_target = triple

    try:
        in_stream, out_stream = await stdio_streams()
    except Exception as exc:  # pragma: no cover — stdio setup very rarely fails
        print(f"failed to open stdio streams: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)

    try:
        await bridge_stdio(
            in_stream,
            out_stream,
            target,
            rewrite_session_new_to_attach=rewrite_target,
        )
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
