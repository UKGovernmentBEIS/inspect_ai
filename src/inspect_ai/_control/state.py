"""Eval-level state extraction for the control channel.

For MVP `inspect ctl ls`, summaries are computed on demand from the
always-on :func:`inspect_ai.log._samples.active_samples` registry.
A proper :class:`EvalState` aggregate (queued / completed counts,
model usage rollup) updated at sample lifecycle transitions lands as
a follow-on — see design/control-channel.md phase 1.

One process can host multiple evals at once (an eval-set passes all
tasks to a single ``eval()`` call, so they share the process and the
``run_id`` but each carries its own ``eval_id``). The endpoint emits
one summary per ``eval_id`` so consumers (the CLI, TUIs, agents) see
each running eval as a distinct row.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample


def current_eval_summaries(run_id: str, started_at: float) -> list[dict[str, Any]]:
    """Build per-eval summaries for the ``GET /evals`` endpoint.

    Args:
        run_id: This process's run id (shared across every eval in
            an eval-set; we filter ``active_samples`` to entries
            whose ``run_id`` matches so two co-resident inspect
            processes don't bleed into each other's surface — though
            the discovery layer already keeps them on separate
            sockets, this is belt-and-suspenders).
        started_at: Fallback start time for evals whose samples
            haven't started yet (rare — there's typically at least
            one started sample by the time we're queried).

    Returns:
        One dict per running eval, sorted by start time (oldest
        first). An eval with zero live samples (eg. all completed but
        scoring still pending) does not appear — see "EvalState
        aggregate" follow-up in the doc.
    """
    # Lazy import to avoid pulling the full log/event/scorer chain at
    # module-import time (control server module is imported during
    # eval bootstrap before those packages finish initialising).
    from inspect_ai.log._samples import active_samples

    groups: dict[str, list[ActiveSample]] = defaultdict(list)
    for sample in active_samples():
        if sample.run_id != run_id:
            continue
        groups[sample.eval_id].append(sample)

    summaries: list[dict[str, Any]] = []
    for eval_id, samples in groups.items():
        # All samples in one eval share the same task name and model
        # (eval = task × model). Pick the first row's values.
        first = samples[0]

        # Eval-level start time = earliest sample start time. Falls
        # back to the process started_at if no sample has started yet
        # (rare: would mean the eval is between samples or in setup).
        sample_starts = [s.started for s in samples if s.started is not None]
        eval_started_at = min(sample_starts) if sample_starts else started_at

        in_flight = sum(
            1 for s in samples if s.started is not None and s.completed is None
        )

        summaries.append(
            {
                "run_id": run_id,
                "eval_id": eval_id,
                "task": first.task,
                "model": first.model,
                "status": "running",
                "started_at": eval_started_at,
                "samples_in_flight": in_flight,
                "total_tokens": sum(s.total_tokens for s in samples),
                "total_messages": sum(s.total_messages for s in samples),
            }
        )

    summaries.sort(key=lambda s: s["started_at"])
    return summaries
