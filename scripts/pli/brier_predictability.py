"""Brier predictability P_brier from an Inspect eval log.

Computes P_brier = 1 - (1/T) * sum_i (c_i - y_i)^2 with confidence c_i in [0, 1] and
binary outcome y_i from the scorer. Unlike P_AUROC, this is defined when all outcomes
are the same.

Uses the same confidence / outcome pairing rules as ``discrimination_predictability.py``.

Usage::

    python scripts/pli/brier_predictability.py --latest --confidence-key confidence --confidence-source sample
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent.parent / "helper_scripts"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

from reliability_common import (
    brier_mse,
    discrimination_pairs_from_log,
    resolve_log_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute Brier predictability P_brier = 1 - mean((confidence - outcome)^2) "
            "from an Inspect eval log."
        )
    )
    parser.add_argument("--log", type=str, default=None, help="Path to .eval log file.")
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument(
        "--scorer",
        type=str,
        default=None,
        help="Scorer name (default: inferred from log).",
    )
    parser.add_argument(
        "--confidence-key",
        type=str,
        required=True,
        help='Dotted metadata key for confidence (e.g. "confidence").',
    )
    parser.add_argument(
        "--confidence-source",
        choices=("score", "sample"),
        default="score",
        help="Read confidence from scorer metadata or sample.metadata (default: score).",
    )
    parser.add_argument(
        "--skip-missing-confidence",
        action="store_true",
        help="Skip samples with missing or invalid confidence instead of failing.",
    )
    parser.add_argument(
        "--no-clamp-confidence",
        action="store_true",
        help="Do not clamp confidence to [0, 1] when outside that range.",
    )
    args = parser.parse_args()

    log_path = resolve_log_path(log=args.log, log_dir=args.log_dir, latest=args.latest)
    with warnings.catch_warnings():
        warnings.simplefilter("default", UserWarning)
        pairs, scorer, n_skip = discrimination_pairs_from_log(
            log_path,
            args.scorer,
            args.confidence_key,
            confidence_source=args.confidence_source,
            skip_missing_confidence=args.skip_missing_confidence,
            clamp_confidence_01=not args.no_clamp_confidence,
        )

    n_succ = sum(y for _, y in pairs if y == 1)
    n_fail = len(pairs) - n_succ
    mse = brier_mse(pairs)
    p_brier = 1.0 - mse

    print(f"log={log_path}")
    print(f"scorer={scorer}")
    print(f"confidence_key={args.confidence_key}")
    print(f"confidence_source={args.confidence_source}")
    print(f"n_pairs={len(pairs)}")
    print(f"n_succ={n_succ}")
    print(f"n_fail={n_fail}")
    if n_skip:
        print(f"skipped_missing_confidence={n_skip}")
    print(f"brier_mse={mse:.6f}")
    print(f"P_brier={p_brier:.6f}")


if __name__ == "__main__":
    main()
