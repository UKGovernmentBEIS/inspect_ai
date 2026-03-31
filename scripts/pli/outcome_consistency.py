"""Compute outcome consistency (C_out) from an Inspect eval log.

This script groups scores by task id across repeated runs and computes:
    C_out = 1 - (sigma_hat^2 / (p_hat * (1 - p_hat) + epsilon))
where p_hat is the mean task success rate and sigma_hat^2 is sample variance.

Usage examples:
    python scripts/pli/outcome_consistency.py --latest
    python scripts/pli/outcome_consistency.py --log logs/my_eval.eval --scorer choice
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent.parent / "helper_scripts"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

from reliability_common import resolve_log_path
from inspect_ai.log import read_eval_log
from inspect_ai.scorer import Score, ScoreReducer, score_reducer, value_to_float


@score_reducer(name="outcome_consistency")
def outcome_consistency(epsilon: float = 1e-8) -> ScoreReducer:
    """Outcome consistency for one task across K runs."""
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


def outcome_from_log(log_path: Path, scorer_name: str | None, epsilon: float) -> float:
    log = read_eval_log(str(log_path))
    if not log.samples:
        raise ValueError(f"Log has no samples: {log_path}")

    if scorer_name is None:
        if log.results and log.results.scores:
            scorer_name = log.results.scores[0].name
        else:
            for sample in log.samples:
                if sample.scores:
                    scorer_name = next(iter(sample.scores.keys()))
                    break
            if scorer_name is None:
                raise ValueError(
                    "Could not infer scorer name from log results or sample scores."
                )

    by_sample_id: dict[str | int, list[Score]] = defaultdict(list)
    for sample in log.samples:
        if not sample.scores or scorer_name not in sample.scores:
            continue
        by_sample_id[sample.id].append(sample.scores[scorer_name])

    if not by_sample_id:
        raise ValueError(f"No sample scores found for scorer '{scorer_name}'.")

    reducer = outcome_consistency(epsilon=epsilon)
    per_task = [reducer(sample_scores).as_float() for sample_scores in by_sample_id.values()]
    return float(sum(per_task) / len(per_task))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute outcome consistency from an Inspect eval log."
    )
    parser.add_argument("--log", type=str, default=None, help="Path to .eval log file.")
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument(
        "--scorer",
        type=str,
        default=None,
        help="Scorer name (default: first scorer in log results).",
    )
    parser.add_argument("--epsilon", type=float, default=1e-8)
    args = parser.parse_args()

    log_path = resolve_log_path(log=args.log, log_dir=args.log_dir, latest=args.latest)
    score = outcome_from_log(log_path=log_path, scorer_name=args.scorer, epsilon=args.epsilon)
    print(f"log={log_path}")
    print(f"outcome_consistency={score:.6f}")


if __name__ == "__main__":
    main()
