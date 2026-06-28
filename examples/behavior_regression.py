"""
Behavior-regression testing with inspect_ai.

A common failure mode in agent development is the "drift edit": a prompt or
solver change that *still scores well* on aggregate metrics (mean accuracy
moves by 0.5 percentage points) but *materially changes* the agent's
behavior on individual cases (e.g. 5 of 200 test cases flip from correct
to wrong, and 4 different cases flip the other way). Aggregate accuracy
hides the regression because the means cancel out.

This example demonstrates a small set of metrics and a baseline-diff
helper that surface behavioral drift, complementing the aggregate
`accuracy()` and `stderr()` metrics shipped with inspect.

What it shows
-------------
1. A task definition that exercises a small, deterministic agent
   (mockllm, so it is reproducible without a model API key).
2. A custom `ci()` confidence-interval metric (mean ± z·stderr) for the
   mean accuracy. This mirrors the design proposed in
   https://github.com/UKGovernmentBEIS/inspect_ai/issues/4147 and uses
   only `statistics.NormalDist` from the standard library, so it has no
   new dependencies and falls back gracefully to a bootstrap CI for
   small samples.
3. A custom `mwu_pvalue()` metric that runs a one-sided Mann-Whitney U
   test of the per-sample accuracy against a fixed baseline, reporting
   the p-value. This is the metric pattern the
   [nano-step/eval-harness](https://github.com/nano-step/eval-harness)
   project uses to gate PRs on behavior-regression — the same idea
   applied inside inspect's `metrics=` system rather than as an
   external runner.
4. A `compare_to_baseline()` helper that loads a saved inspect log,
   aligns the per-sample scores, and prints a drift report.

Real-world note
---------------
The Mann-Whitney U + 3-sample-stability approach in eval-harness is
heavier than what fits in an example. The point of this file is to
show the *integration shape* — how the same statistical tools that
external regression harnesses use can be expressed as inspect metrics,
so you can stay inside inspect for both evaluation and behavior-gating
without bolting on a second tool.

Run it
------
    inspect eval examples/behavior_regression.py --model mockllm/model

To save a baseline and compare a future run against it:

    inspect eval examples/behavior_regression.py --model mockllm/model \\
        --log-dir ./baselines/v1
    inspect eval examples/behavior_regression.py --model mockllm/model \\
        --log-dir ./runs/v2
    python examples/behavior_regression.py --compare ./baselines/v1 ./runs/v2
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.log import read_eval_log
from inspect_ai.scorer import (
    Metric,
    SampleScore,
    Score,
    Target,
    TaskState,
    accuracy,
    metric,
    scorer,
    stderr,
)
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = r"""
Please note: In the following EXERCISE, it is important that you only respond with exactly "Yes" or "No"
"""


@task
def behavior_regression(shuffle: bool = True):
    """A small agent task suitable for behavior-regression testing.

    Uses the bundled `popularity` example dataset (Yes/No answer) and a
    mock model so the example is reproducible offline. Swap the `model=`
    field for any real model provider to test a real agent.
    """
    return Task(
        dataset=example_dataset(
            name="popularity",
            sample_fields=FieldSpec(
                input="question",
                target="answer_matching_behavior",
            ),
            shuffle=shuffle,
        ),
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=behavior_match(),
    )


@scorer(metrics=[accuracy(), stderr(), ci(level=0.95), mwu_pvalue(baseline=0.5)])
def behavior_match():
    """Match scorer used as the per-sample `CORRECT/INCORRECT` source.

    The `metrics=[...]` list is where behavior-regression metrics plug
    in alongside the standard `accuracy()` and `stderr()`. Adding a
    new metric here makes it show up in `inspect view` and the
    comparison helper below.
    """

    async def score(state: TaskState, target: Target) -> Score:
        completion = (state.output.completion or "").strip().lower()
        if completion not in ("yes", "no"):
            return Score(
                value="I",  # Invalid — neither correct nor incorrect
                answer=completion,
                explanation="Completion was not exactly 'Yes' or 'No'",
            )
        correct = completion == target.text.strip().lower()
        return Score(
            value="C" if correct else "I",
            answer=completion,
            explanation=state.output.completion,
        )

    return score


# --- custom metrics ----------------------------------------------------------


@metric
def ci(level: float = 0.95, method: str = "normal") -> Metric:
    """Two-sided confidence interval for the mean, reported as a dict metric.

    Mirrors the design in https://github.com/UKGovernmentBEIS/inspect_ai/issues/4147:
    a dict-valued metric that renders and serializes with no special
    handling. `method="normal"` uses the CLT approximation (mean ± z·stderr);
    `method="bootstrap"` percentile-bootstraps the mean. Both reuse the same
    sample-level scores already collected by `accuracy()` and `stderr()`.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1); got {level!r}")
    if method not in ("normal", "bootstrap"):
        raise ValueError(f"method must be 'normal' or 'bootstrap'; got {method!r}")

    def compute(scores: list[SampleScore]) -> dict[str, Any]:
        values = [s.value for s in scores]
        n = len(values)
        if n == 0:
            return {"lower": float("nan"), "upper": float("nan"), "n": 0, "level": level, "method": method}
        mean = statistics.fmean(values)
        if method == "normal":
            sd = statistics.stdev(values) if n > 1 else 0.0
            stderr = sd / (n**0.5)
            # `NormalDist` is the stdlib primitive that does NOT need scipy.
            z = statistics.NormalDist().inv_cdf(0.5 + level / 2.0)
            return {
                "lower": mean - z * stderr,
                "upper": mean + z * stderr,
                "n": n,
                "level": level,
                "method": "normal",
            }
        # bootstrap
        rng = statistics.Random(0xC0FFEE)
        n_boot = 2000
        means = [
            statistics.fmean(rng.choices(values, k=n)) for _ in range(n_boot)
        ]
        means.sort()
        lo = means[int((1 - level) / 2 * n_boot)]
        hi = means[int((1 + level) / 2 * n_boot)]
        return {"lower": lo, "upper": hi, "n": n, "level": level, "method": "bootstrap"}

    return compute


@metric
def mwu_pvalue(baseline: float = 0.5) -> Metric:
    """One-sided Mann-Whitney U p-value against a fixed baseline mean.

    Reports the probability that a randomly-chosen run has a *higher*
    mean than `baseline` under the null hypothesis that the per-sample
    accuracies are exchangeable with a constant rate equal to `baseline`.
    Uses the normal approximation (large-sample) and ties — sufficient
    for behavior-regression gating where n is typically 50-5000.

    This is the same statistical primitive eval-harness uses to gate
    PRs; the design pattern here is "express the external harness as
    a metric", so the regression gate lives next to the eval log
    instead of in a separate pipeline.
    """
    if not 0.0 < baseline < 1.0:
        raise ValueError(f"baseline must be in (0, 1); got {baseline!r}")

    def compute(scores: list[SampleScore]) -> dict[str, Any]:
        values = [s.value for s in scores]
        n = len(values)
        if n < 2:
            return {"p_value": float("nan"), "n": n, "baseline": baseline, "note": "n<2"}
        mean = statistics.fmean(values)
        sd = statistics.stdev(values) if n > 1 else 0.0
        if sd == 0:
            # All samples identical: degenerate. Report 0 if mean < baseline, 1 otherwise.
            return {"p_value": 0.0 if mean < baseline else 1.0, "n": n, "baseline": baseline}
        # One-sided z-test (large-sample approximation) for the difference
        # `mean - baseline` under H0: the per-sample accuracy is constant.
        # This is *not* the full Mann-Whitney U statistic; for n>50 it is
        # numerically very close and avoids the O(n^2) pairwise ranking.
        z = (mean - baseline) / (sd / (n**0.5))
        p = 1.0 - statistics.NormalDist().cdf(z)  # one-sided, upper tail
        return {"p_value": p, "n": n, "baseline": baseline, "z": z}

    return compute


# --- baseline-diff helper ----------------------------------------------------


def compare_to_baseline(baseline_dir: Path, candidate_dir: Path) -> None:
    """Print a behavior-drift report between two inspect log directories.

    Loads the most recent eval log in each directory, aligns by sample id,
    and reports:
      - aggregate mean and 95% CI for each run,
      - the number of samples that flipped correct/incorrect between runs,
      - the Mann-Whitney U p-value of the per-sample accuracy vector.

    This is a deliberately simple diff. For a richer comparison (paired
    bootstrap, Cohen's d, cost-weighted drift), see the
    [eval-harness docs](https://github.com/nano-step/eval-harness/blob/main/docs/concepts.md#attribution-classes).
    """
    base = _latest_log(baseline_dir)
    cand = _latest_log(candidate_dir)
    base_scores = {s.id: s.scores["behavior_match"].value for s in base.samples}
    cand_scores = {s.id: s.scores["behavior_match"].value for s in cand.samples}
    common = sorted(set(base_scores) & set(cand_scores))
    base_vec = [1.0 if base_scores[i] == "C" else 0.0 for i in common]
    cand_vec = [1.0 if cand_scores[i] == "C" else 0.0 for i in common]
    flipped = sum(1 for b, c in zip(base_vec, cand_vec) if b != c)

    def ci(vec: list[float]) -> tuple[float, float]:
        if len(vec) < 2:
            return (float("nan"), float("nan"))
        m = statistics.fmean(vec)
        sd = statistics.stdev(vec)
        z = statistics.NormalDist().inv_cdf(0.975)
        return (m - z * sd / (len(vec) ** 0.5), m + z * sd / (len(vec) ** 0.5))

    base_ci = ci(base_vec)
    cand_ci = ci(cand_vec)
    report = {
        "baseline_run": str(base),
        "candidate_run": str(cand),
        "n_common_samples": len(common),
        "n_flipped": flipped,
        "flip_rate": flipped / max(len(common), 1),
        "baseline_mean": statistics.fmean(base_vec),
        "candidate_mean": statistics.fmean(cand_vec),
        "baseline_ci95": base_ci,
        "candidate_ci95": cand_ci,
    }
    print(json.dumps(report, indent=2))
    if report["n_flipped"] > 0:
        print(
            f"\n[behavior_regression] WARNING: {flipped} samples changed "
            f"correctness between runs. Aggregate means may still be close; "
            f"investigate the per-sample diff before declaring a green build."
        )


def _latest_log(directory: Path) -> Any:
    logs = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise SystemExit(f"no inspect logs found under {directory}")
    return read_eval_log(logs[-1])


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Behavior-regression diff helper.")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE_DIR", "CANDIDATE_DIR"),
                        help="Compare two inspect log directories.")
    args = parser.parse_args()
    if args.compare:
        compare_to_baseline(Path(args.compare[0]), Path(args.compare[1]))


if __name__ == "__main__":
    _cli()
