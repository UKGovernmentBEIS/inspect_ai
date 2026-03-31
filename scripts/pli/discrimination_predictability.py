r"""Discrimination predictability :math:`P_{\mathrm{AUROC}}` from an Inspect eval log.

Fraction of (success, failure) sample pairs where the successful sample's reported
confidence is **strictly greater** than the failed sample's—equivalent to AUC-ROC
for confidence vs. binary outcome. If every sample has the same outcome (all correct
or all incorrect), ``P_AUROC`` is undefined; the script prints ``P_AUROC=undefined``
and the class counts instead of raising.

Each sample must expose a numeric confidence in score metadata (default) or sample
metadata, e.g. ``scores["choice"].metadata["confidence"]``. Populate this from a
custom scorer, model logprobs, or post-processing.

Usage::

    python scripts/pli/discrimination_predictability.py --latest --confidence-key confidence
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
    discrimination_p_auroc,
    discrimination_pairs_from_log,
    resolve_log_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute discrimination P_AUROC from confidence and binary outcomes in an "
            "Inspect eval log."
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
        help='Dotted metadata key for confidence (e.g. "confidence" or "model.p_correct").',
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

    print(f"log={log_path}")
    print(f"scorer={scorer}")
    print(f"confidence_key={args.confidence_key}")
    print(f"confidence_source={args.confidence_source}")
    print(f"n_pairs={len(pairs)}")
    print(f"n_succ={n_succ}")
    print(f"n_fail={n_fail}")
    if n_skip:
        print(f"skipped_missing_confidence={n_skip}")
    if n_succ == 0 or n_fail == 0:
        print(
            "P_AUROC=undefined (needs both correct and incorrect scored samples; "
            "AUC is not defined with a single outcome class)."
        )
        return

    p_auroc = discrimination_p_auroc(pairs)
    print(f"P_AUROC={p_auroc:.6f}")


if __name__ == "__main__":
    main()
