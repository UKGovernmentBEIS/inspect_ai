"""Eval-level state extraction for the control channel.

For MVP `inspect ctl ls`, the response is computed on demand from the
always-on :func:`inspect_ai.log._samples.active_samples` registry.
A proper :class:`EvalState` aggregate (queued / completed counts,
model usage rollup, etc.) updated at sample lifecycle transitions
lands as a follow-on — see design/control-channel.md phase 1.
"""

from __future__ import annotations

from typing import Any


def current_eval_summary(run_id: str, started_at: float) -> dict[str, Any]:
    """Build a single-eval summary dict for the GET /evals endpoint.

    Aggregates live :class:`ActiveSample` rows for this run into the
    summary shape `inspect ctl ls` consumes. The current process serves
    exactly one eval at a time (multi-task evals collapse into one
    summary; eval-set lifecycle hoisting is a later phase).
    """
    # Lazy import to avoid pulling the full log/event/scorer chain at
    # module-import time — control server module is imported during
    # eval bootstrap before those packages finish initialising.
    from inspect_ai.log._samples import active_samples

    samples = [s for s in active_samples() if s.run_id == run_id]

    tasks = sorted({s.task for s in samples})
    models = sorted({s.model for s in samples if s.model})
    total_tokens = sum(s.total_tokens for s in samples)
    total_messages = sum(s.total_messages for s in samples)
    in_flight = sum(1 for s in samples if s.started is not None and s.completed is None)

    return {
        "run_id": run_id,
        "tasks": tasks,
        "models": models,
        "status": "running",
        "started_at": started_at,
        "samples_in_flight": in_flight,
        "total_tokens": total_tokens,
        "total_messages": total_messages,
    }
