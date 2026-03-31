r"""Compute prompt robustness R_prompt from two Inspect eval logs.

R_prompt = min(Acc_para / Acc_0, 1) where Acc_0 is baseline accuracy and Acc_para is
accuracy when prompts are paraphrased (same tasks and scorer).

Usage::

    python scripts/pli/prompt_robustness.py --baseline-log logs/base.eval --paraphrase-log logs/para.eval
    python scripts/pli/prompt_robustness.py --baseline-latest --paraphrase-latest \\
        --baseline-log-dir logs/baseline --paraphrase-log-dir logs/paraphrase
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent.parent / "helper_scripts"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

from reliability_common import (
    accuracy_from_log,
    clamped_accuracy_ratio,
    resolve_optional_log,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute prompt robustness R_prompt from baseline and paraphrase logs."
    )
    parser.add_argument("--baseline-log", type=str, default=None)
    parser.add_argument("--paraphrase-log", type=str, default=None)
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--baseline-log-dir", type=str, default=None)
    parser.add_argument("--paraphrase-log-dir", type=str, default=None)
    parser.add_argument("--baseline-latest", action="store_true")
    parser.add_argument("--paraphrase-latest", action="store_true")
    parser.add_argument("--scorer", type=str, default=None)
    args = parser.parse_args()

    baseline_log_dir = args.baseline_log_dir or args.log_dir
    paraphrase_log_dir = args.paraphrase_log_dir or args.log_dir
    baseline_path = resolve_optional_log(
        args.baseline_log, baseline_log_dir, args.baseline_latest, "baseline"
    )
    paraphrase_path = resolve_optional_log(
        args.paraphrase_log, paraphrase_log_dir, args.paraphrase_latest, "paraphrase"
    )

    acc_0, scorer_0 = accuracy_from_log(baseline_path, args.scorer)
    acc_p, scorer_p = accuracy_from_log(paraphrase_path, args.scorer)
    if scorer_0 != scorer_p:
        raise ValueError(
            f"Scorer mismatch: baseline uses '{scorer_0}', paraphrase uses '{scorer_p}'."
        )

    r_prompt = clamped_accuracy_ratio(acc_0, acc_p)
    print(f"baseline_log={baseline_path}")
    print(f"paraphrase_log={paraphrase_path}")
    print(f"scorer={scorer_0}")
    print(f"acc_baseline={acc_0:.6f}")
    print(f"acc_paraphrase={acc_p:.6f}")
    print(f"R_prompt={r_prompt:.6f}")


if __name__ == "__main__":
    main()
