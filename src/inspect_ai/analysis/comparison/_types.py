"""Data types for evaluation comparison results."""

from __future__ import annotations

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
        return sum(
            1
            for s in self.samples
            if s.direction in ("improved", "regressed", "unchanged")
        )

    @property
    def missing_count(self) -> int:
        """Samples in baseline but not in candidate."""
        return sum(1 for s in self.samples if s.direction == "missing")

    @property
    def new_count(self) -> int:
        """Samples in candidate but not in baseline."""
        return sum(1 for s in self.samples if s.direction == "new")

    def summary(self) -> str:
        """Generate a text summary of the comparison."""
        lines = [
            f"Comparison: {self.baseline_model} vs {self.candidate_model}",
            f"Task: {self.baseline_task}",
            f"Samples: {self.aligned_count} aligned, "
            f"{self.missing_count} missing, {self.new_count} new",
            "",
        ]

        if self.metrics:
            lines.append("Metrics:")
            for m in self.metrics:
                sig = "*" if m.significant else ""
                rel = (
                    f" ({m.relative_delta:+.1%})"
                    if m.relative_delta is not None
                    else ""
                )
                lines.append(
                    f"  {m.scorer}/{m.name}: "
                    f"{m.baseline_value:.4f} -> {m.candidate_value:.4f} "
                    f"(delta: {m.delta:+.4f}{rel}){sig}"
                )
            lines.append("")

        reg_count = len(self.regressions)
        imp_count = len(self.improvements)
        unch_count = len(self.unchanged)
        lines.append(
            f"Regressions: {reg_count}, Improvements: {imp_count}, "
            f"Unchanged: {unch_count}"
        )

        return "\n".join(lines)
