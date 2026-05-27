"""Eval-level state extraction for the control channel.

Reads from two sources at request time:

- :func:`inspect_ai.log._eval_state.get_eval_states` for ``total`` /
  ``completed`` / ``errored`` counters that survive a sample exiting
  ``active_samples``.
- :func:`inspect_ai.log._samples.active_samples` for ``in_flight``
  (currently-executing samples), plus the per-eval ``task`` / ``model``
  / ``started_at`` metadata.

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
        run_id: This process's run id. Filters ``active_samples`` and
            ``EvalState`` entries to this run so two co-resident
            inspect processes don't bleed into each other (the
            discovery layer also keeps them on separate sockets —
            this is belt-and-suspenders).
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

    # Group live samples by eval_id (run-scoped).
    samples_by_eval: dict[str, list[ActiveSample]] = defaultdict(list)
    for sample in active_samples():
        if sample.run_id != run_id:
            continue
        samples_by_eval[sample.eval_id].append(sample)

    # EvalState entries — the source of truth for terminal counts.
    # Filter by run_id where possible. The eval_state module doesn't
    # store run_id (it's keyed by eval_id), so we cross-reference
    # via the active samples we just collected. For an eval with no
    # active samples (eg. between samples), we have to skip it here
    # — it'll come back once another sample starts. The follow-up
    # design is to put run_id directly on EvalState.
    eval_states = {state.eval_id: state for state in get_eval_states()}

    # Eval ids to summarize: union of live samples and known states
    # filtered to those that match this run via active_samples.
    eval_ids = set(samples_by_eval.keys())

    summaries: list[dict[str, Any]] = []
    for eval_id in eval_ids:
        samples = samples_by_eval.get(eval_id, [])
        state = eval_states.get(eval_id)

        if not samples and state is None:
            continue

        # Per-eval metadata comes from the first sample (all samples
        # in one eval share task name + model).
        first_sample = samples[0] if samples else None
        task_name = first_sample.task if first_sample else ""
        model = first_sample.model if first_sample else ""

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
