"""Sample alignment across evaluation runs.

Aligns samples between two eval logs by (id, epoch) key, matching
Inspect's own retry logic at _eval/task/run.py:1345.
"""

from __future__ import annotations

from dataclasses import dataclass
from logging import getLogger
from typing import Any

from inspect_ai.log._log import EvalLog, EvalSample

logger = getLogger(__name__)


@dataclass
class AlignedSample:
    """A pair of samples aligned by (id, epoch)."""

    id: int | str
    epoch: int
    baseline: EvalSample | None
    candidate: EvalSample | None


def align_samples(
    baseline_log: EvalLog,
    candidate_log: EvalLog,
) -> list[AlignedSample]:
    """Align samples from two eval logs by (id, epoch).

    Samples are matched using the same (id, epoch) key that Inspect
    uses internally for eval retry sample reuse. Samples present in
    only one log are included with None for the missing side.

    Args:
        baseline_log: The baseline evaluation log.
        candidate_log: The candidate evaluation log.

    Returns:
        List of AlignedSample pairs, ordered by (id, epoch).
    """
    baseline_samples = baseline_log.samples or []
    candidate_samples = candidate_log.samples or []

    baseline_map: dict[tuple[Any, int], EvalSample] = {
        (_sample_key(s.id), s.epoch): s for s in baseline_samples
    }
    candidate_map: dict[tuple[Any, int], EvalSample] = {
        (_sample_key(s.id), s.epoch): s for s in candidate_samples
    }

    all_keys = sorted(
        set(baseline_map.keys()) | set(candidate_map.keys()),
        key=lambda k: (str(k[0]), k[1]),
    )

    aligned: list[AlignedSample] = []
    for key in all_keys:
        sample_id, epoch = key
        aligned.append(
            AlignedSample(
                id=sample_id,
                epoch=epoch,
                baseline=baseline_map.get(key),
                candidate=candidate_map.get(key),
            )
        )

    baseline_only = sum(1 for a in aligned if a.candidate is None)
    candidate_only = sum(1 for a in aligned if a.baseline is None)
    matched = sum(
        1 for a in aligned if a.baseline is not None and a.candidate is not None
    )

    logger.info(
        "Aligned %d samples: %d matched, %d baseline-only, %d candidate-only",
        len(aligned),
        matched,
        baseline_only,
        candidate_only,
    )

    return aligned


def _sample_key(sample_id: int | str) -> int | str:
    """Normalize sample ID for consistent alignment.

    Matches the normalization pattern from dataset/_util.py:normalise_sample_id.
    """
    if isinstance(sample_id, str) and sample_id.isdigit():
        return int(sample_id)
    return sample_id
