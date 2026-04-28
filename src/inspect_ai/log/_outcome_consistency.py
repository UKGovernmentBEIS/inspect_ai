"""Outcome consistency (C_out) for eval logs: aggregate metric and metadata helpers."""

from __future__ import annotations

import getpass
from collections import defaultdict
from pathlib import Path

from inspect_ai.log._edit import MetadataEdit, ProvenanceData, edit_eval_log
from inspect_ai.log._file import read_eval_log, write_eval_log
from inspect_ai.log._log import EvalLog
from inspect_ai.scorer import Score, ScoreReducer, value_to_float


def make_outcome_consistency_reducer(epsilon: float = 1e-8) -> ScoreReducer:
    """Reducer for C_out for one sample id across K epochs/runs (no task registry)."""
    to_float = value_to_float()

    def reduce(scores: list[Score]) -> Score:
        values = [to_float(score.value) for score in scores]
        count = len(values)
        if count < 2:
            return Score(value=1.0)

        p_hat = sum(values) / count
        variance = sum((value - p_hat) ** 2 for value in values) / (count - 1)
        denom = p_hat * (1.0 - p_hat) + epsilon
        c_out = 1.0 - (variance / denom)
        c_out = max(0.0, min(1.0, c_out))
        return Score(value=float(c_out))

    return reduce


def _resolve_scorer_name(log: EvalLog, scorer_name: str | None) -> str:
    if scorer_name is not None:
        return scorer_name
    if log.results and log.results.scores:
        return log.results.scores[0].name
    for sample in log.samples or []:
        if sample.scores:
            return next(iter(sample.scores.keys()))
    raise ValueError(
        "Could not infer scorer name from log results or sample scores; pass scorer_name explicitly."
    )


def outcome_consistency_value_for_log(
    log: EvalLog, scorer_name: str | None, epsilon: float
) -> tuple[float, str]:
    """Return aggregate C_out and the scorer name used.

    C_out is the mean, over sample ids, of per-id outcome consistency.
    """
    if not log.samples:
        raise ValueError("Log has no samples")

    name = _resolve_scorer_name(log, scorer_name)

    by_sample_id: dict[str | int, list[Score]] = defaultdict(list)
    for sample in log.samples:
        if not sample.scores or name not in sample.scores:
            continue
        by_sample_id[sample.id].append(sample.scores[name])

    if not by_sample_id:
        raise ValueError(f"No sample scores found for scorer '{name}'.")

    reducer = make_outcome_consistency_reducer(epsilon=epsilon)
    per_task = [
        reducer(sample_scores).as_float() for sample_scores in by_sample_id.values()
    ]
    return float(sum(per_task) / len(per_task)), name


def apply_outcome_consistency_metadata(
    log: EvalLog,
    *,
    scorer_name: str | None = None,
    epsilon: float = 1e-8,
    metadata_key: str = "outcome_consistency",
    scorer_metadata_key: str = "outcome_consistency_scorer",
    include_scorer_in_metadata: bool = True,
    author: str | None = None,
    reason: str | None = None,
) -> EvalLog:
    """Apply a metadata edit to ``log`` with C_out (and optionally the scorer name used)."""
    value, resolved_scorer = outcome_consistency_value_for_log(
        log, scorer_name=scorer_name, epsilon=epsilon
    )
    meta: dict[str, object] = {metadata_key: value}
    if include_scorer_in_metadata:
        meta[scorer_metadata_key] = resolved_scorer
    provenance = ProvenanceData(
        author=author or getpass.getuser(),
        reason=reason,
    )
    return edit_eval_log(
        log,
        [MetadataEdit(metadata_set=meta)],
        provenance,
    )


def write_outcome_consistency_to_eval_file(
    path: str | Path,
    *,
    scorer_name: str | None = None,
    epsilon: float = 1e-8,
    metadata_key: str = "outcome_consistency",
    scorer_metadata_key: str = "outcome_consistency_scorer",
    include_scorer_in_metadata: bool = True,
    author: str | None = None,
    reason: str | None = None,
) -> None:
    """Read a log from disk, append C_out metadata, and write back in place."""
    location = path.as_posix() if isinstance(path, Path) else str(path)
    log = read_eval_log(location, header_only=False)
    etag = log.etag
    updated = apply_outcome_consistency_metadata(
        log,
        scorer_name=scorer_name,
        epsilon=epsilon,
        metadata_key=metadata_key,
        scorer_metadata_key=scorer_metadata_key,
        include_scorer_in_metadata=include_scorer_in_metadata,
        author=author,
        reason=reason,
    )
    write_eval_log(updated, location, if_match_etag=etag)
