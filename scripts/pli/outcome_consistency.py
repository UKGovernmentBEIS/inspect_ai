"""Compute outcome consistency (C_out) from an Inspect eval log.

This script groups scores by sample id across repeated runs and computes:
    C_out = 1 - (sigma_hat^2 / (p_hat * (1 - p_hat) + epsilon))
where p_hat is the mean task success rate and sigma_hat^2 is sample variance.

Usage examples:
    python scripts/pli/outcome_consistency.py --latest
    python scripts/pli/outcome_consistency.py --log logs/my_eval.eval --scorer choice
    python scripts/pli/outcome_consistency.py --log logs/my_eval.eval --write-metadata
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent.parent / "helper_scripts"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

from reliability_common import resolve_log_path  # noqa: E402

from inspect_ai.log import (  # noqa: E402
    apply_outcome_consistency_metadata,
    make_outcome_consistency_reducer,
    outcome_consistency_value_for_log,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.scorer import ScoreReducer, score_reducer  # noqa: E402


@score_reducer(name="outcome_consistency")
def outcome_consistency(epsilon: float = 1e-8) -> ScoreReducer:
    """Outcome consistency for one task across K runs (registry entry for tasks)."""
    return make_outcome_consistency_reducer(epsilon=epsilon)


def outcome_from_log(log_path: Path, scorer_name: str | None, epsilon: float) -> float:
    log = read_eval_log(str(log_path))
    return outcome_consistency_value_for_log(log, scorer_name, epsilon)[0]


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
    parser.add_argument(
        "--write-metadata",
        action="store_true",
        help="Append C_out to log metadata (via edit_eval_log) and write the file in place.",
    )
    parser.add_argument(
        "--metadata-key",
        type=str,
        default="outcome_consistency",
        help="Metadata key for C_out when using --write-metadata.",
    )
    parser.add_argument(
        "--no-scorer-in-metadata",
        action="store_true",
        help="Do not set outcome_consistency_scorer in metadata when using --write-metadata.",
    )
    args = parser.parse_args()

    log_path = resolve_log_path(log=args.log, log_dir=args.log_dir, latest=args.latest)
    if args.write_metadata:
        log = read_eval_log(str(log_path), header_only=False)
        before_etag = log.etag
        updated = apply_outcome_consistency_metadata(
            log,
            scorer_name=args.scorer,
            epsilon=args.epsilon,
            metadata_key=args.metadata_key,
            include_scorer_in_metadata=not args.no_scorer_in_metadata,
            reason="scripts/pli/outcome_consistency.py --write-metadata",
        )
        write_eval_log(updated, str(log_path), if_match_etag=before_etag)
        value = float(updated.metadata[args.metadata_key])
    else:
        value = outcome_from_log(
            log_path=log_path, scorer_name=args.scorer, epsilon=args.epsilon
        )

    print(f"log={log_path}")
    print(f"outcome_consistency={value:.6f}")


if __name__ == "__main__":
    main()
