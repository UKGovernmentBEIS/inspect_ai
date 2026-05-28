r"""Eval-level state extraction for the control channel.

Reads from two sources at request time:

- :func:`inspect_ai.log._eval_state.get_eval_states` for ``total`` /
  ``completed`` / ``errored`` counters that survive a sample exiting
  ``active_samples``.
- :func:`inspect_ai.log._samples.active_samples` for ``in_flight``
  (currently-executing samples), plus the per-eval ``task`` / ``model``
  / ``started_at`` / ``run_id`` metadata.

One process can host multiple evals at once. There are two ways this
happens:

- Inside a single ``eval()`` call with multiple tasks (an eval-set
  passes all tasks in one call). All share the same ``run_id`` but
  carry distinct ``eval_id``\s.
- Across multiple ``eval()`` calls in an eval-set (across retries).
  Each call has its own ``run_id``; the (eval-set-scoped) control
  server stays bound across them.

The endpoint emits one summary per ``eval_id`` so consumers see each
running eval as a distinct row regardless of which case applies.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample


def current_eval_summaries(started_at: float) -> list[dict[str, Any]]:
    """Build per-eval summaries for the ``GET /evals`` endpoint.

    No ``run_id`` filter — the discovery layer already scopes
    visibility per process (each running inspect process has its own
    AF_UNIX socket / discovery file), so all entries from
    ``active_samples`` are this process's. Within the process, an
    eval-set may span multiple ``run_id``s; we emit one entry per
    ``eval_id`` and carry that eval's run_id along.

    Args:
        started_at: Fallback start time for evals whose samples
            haven't started yet.

    Returns:
        One dict per running eval, sorted by start time (oldest
        first). Each entry includes a nested ``samples`` block:
        ``{total, completed, errored, in_flight, queued}``.
    """
    # Lazy imports to avoid pulling the full log/event/scorer chain at
    # module-import time (control server module is imported during
    # eval bootstrap before those packages finish initialising).
    from inspect_ai.log._eval_state import get_eval_states
    from inspect_ai.log._samples import active_samples

    # Group live samples by eval_id.
    samples_by_eval: dict[str, list[ActiveSample]] = defaultdict(list)
    for sample in active_samples():
        samples_by_eval[sample.eval_id].append(sample)

    # EvalState entries — the source of truth for terminal counts.
    eval_states = {state.eval_id: state for state in get_eval_states()}

    # Union: evals visible via either source.
    eval_ids = set(samples_by_eval.keys()) | set(eval_states.keys())

    summaries: list[dict[str, Any]] = []
    for eval_id in eval_ids:
        samples = samples_by_eval.get(eval_id, [])
        state = eval_states.get(eval_id)

        # Per-eval metadata: prefer the live sample (most authoritative)
        # but fall back to EvalState's stored labels when no samples
        # remain (typical post-completion keep-alive state). EvalState
        # is populated at task start, so it always has the labels.
        first_sample = samples[0] if samples else None
        task_name = first_sample.task if first_sample else (state.task if state else "")
        model = first_sample.model if first_sample else (state.model if state else "")
        run_id = (
            first_sample.run_id if first_sample else (state.run_id if state else None)
        )

        # Eval-level start time = earliest sample start. Falls back
        # to the process started_at if no sample has started yet.
        sample_starts = [s.started for s in samples if s.started is not None]
        eval_started_at = min(sample_starts) if sample_starts else started_at

        in_flight = sum(
            1 for s in samples if s.started is not None and s.completed is None
        )
        total = state.total if state is not None else 0
        completed = state.completed if state is not None else 0
        errored = state.errored if state is not None else 0
        queued = max(0, total - completed - errored - in_flight)

        summaries.append(
            {
                "run_id": run_id,
                "eval_id": eval_id,
                "task": task_name,
                "model": model,
                "status": "running",
                "started_at": eval_started_at,
                "samples": {
                    "total": total,
                    "completed": completed,
                    "errored": errored,
                    "in_flight": in_flight,
                    "queued": queued,
                },
                "total_tokens": sum(s.total_tokens for s in samples),
                "total_messages": sum(s.total_messages for s in samples),
            }
        )

    summaries.sort(key=lambda s: s["started_at"])
    return summaries
