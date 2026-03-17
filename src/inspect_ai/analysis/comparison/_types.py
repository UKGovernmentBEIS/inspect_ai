"""Data types for evaluation comparison results."""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MetricComparison:
    """Comparison of an aggregate metric between two evaluation runs."""

    name: str
    """Metric name (e.g., 'accuracy', 'mean')."""

    scorer: str
    """Scorer that produced this metric."""

    baseline_value: float
    """Metric value in the baseline run."""

    candidate_value: float
    """Metric value in the candidate run."""

    delta: float
    """Absolute difference (candidate - baseline)."""

    relative_delta: float | None
    """Relative change as a fraction (delta / baseline). None if baseline is zero."""

    significant: bool
    """Whether the difference is statistically significant."""

    p_value: float | None
    """P-value from significance test. None if not computed."""

    ci_lower: float | None
    """Lower bound of confidence interval for the difference."""

    ci_upper: float | None
    """Upper bound of confidence interval for the difference."""

    effect_size: float | None = None
    """Cohen's d effect size. None if not computed."""


@dataclass
class SampleComparison:
    """Comparison of a single sample's score between two runs."""

    id: int | str
    """Sample ID."""

    epoch: int
    """Epoch number."""

    scorer: str
    """Scorer that produced this score."""

    baseline_score: float | None
    """Score value in the baseline run. None if sample missing from baseline."""

    candidate_score: float | None
    """Score value in the candidate run. None if sample missing from candidate."""

    delta: float | None
    """Score difference (candidate - baseline). None if either score is missing."""

    direction: Literal["improved", "regressed", "unchanged", "new", "missing"]
    """Classification of the score change between runs."""


@dataclass
class ComparisonResult:
    """Complete comparison of two evaluation runs."""

    baseline_log: str
    """Path to baseline log file."""

    candidate_log: str
    """Path to candidate log file."""

    baseline_task: str
    """Task name from baseline."""

    candidate_task: str
    """Task name from candidate."""

    baseline_model: str
    """Model name from baseline."""

    candidate_model: str
    """Model name from candidate."""

    metrics: list[MetricComparison] = field(default_factory=list)
    """Aggregate metric comparisons."""

    samples: list[SampleComparison] = field(default_factory=list)
    """Per-sample score comparisons."""

    @functools.cached_property
    def _direction_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "improved": 0,
            "regressed": 0,
            "unchanged": 0,
            "new": 0,
            "missing": 0,
        }
        for s in self.samples:
            counts[s.direction] += 1
        return counts

    @property
    def regressions(self) -> list[SampleComparison]:
        """Samples where the candidate scored lower than baseline."""
        return [s for s in self.samples if s.direction == "regressed"]

    @property
    def improvements(self) -> list[SampleComparison]:
        """Samples where the candidate scored higher than baseline."""
        return [s for s in self.samples if s.direction == "improved"]

    @property
    def unchanged(self) -> list[SampleComparison]:
        """Samples with identical scores in both runs."""
        return [s for s in self.samples if s.direction == "unchanged"]

    @property
    def aligned_count(self) -> int:
        """Number of samples present in both runs."""
        c = self._direction_counts
        return c["improved"] + c["regressed"] + c["unchanged"]

    @property
    def missing_count(self) -> int:
        """Samples in baseline but not in candidate."""
        return self._direction_counts["missing"]

    @property
    def new_count(self) -> int:
        """Samples in candidate but not in baseline."""
        return self._direction_counts["new"]

    @property
    def win_rate(self) -> float | None:
        """Fraction of aligned samples where candidate outperformed baseline."""
        aligned = self.aligned_count
        if aligned == 0:
            return None
        return self._direction_counts["improved"] / aligned

    def summary(self) -> str:
        """Generate a text summary of the comparison."""
        lines = [
            f"Baseline:  {self.baseline_model} ({self.baseline_task})",
            f"Candidate: {self.candidate_model} ({self.candidate_task})",
            f"Samples:   {self.aligned_count} aligned, "
            f"{self.missing_count} missing, {self.new_count} new",
            "",
        ]

        if self.metrics:
            lines.append(
                f"{'Metric':<30} {'Baseline':>10} {'Candidate':>10} "
                f"{'Delta':>10} {'Sig.':>8}"
            )
            lines.append("-" * 72)
            for m in self.metrics:
                sig_str = ""
                if m.p_value is not None:
                    sig_str = f"p={m.p_value:.3f}" if not m.significant else f"p={m.p_value:.3f}*"
                effect = ""
                if m.effect_size is not None:
                    d = abs(m.effect_size)
                    size = "small" if d < 0.5 else ("medium" if d < 0.8 else "large")
                    effect = f" ({size})"
                delta_str = f"{m.delta:+.4f}"
                if m.relative_delta is not None:
                    delta_str += f" ({m.relative_delta:+.1%})"
                lines.append(
                    f"  {m.scorer}/{m.name:<26} {m.baseline_value:>10.4f} "
                    f"{m.candidate_value:>10.4f} {delta_str:>10} {sig_str:>8}{effect}"
                )
            lines.append("")

        c = self._direction_counts
        lines.append(
            f"Regressions: {c['regressed']}, "
            f"Improvements: {c['improved']}, "
            f"Unchanged: {c['unchanged']}"
        )

        if self.win_rate is not None:
            lines.append(
                f"Candidate won on {self._direction_counts['improved']} "
                f"of {self.aligned_count} samples ({self.win_rate:.1%})"
            )

        return "\n".join(lines)
