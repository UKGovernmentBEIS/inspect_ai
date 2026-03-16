"""Evaluation comparison and regression detection.

Compare results from two evaluation runs to detect score regressions,
compute statistical significance, and generate comparison reports.

Example usage:

    from inspect_ai.analysis.comparison import compare_evals

    result = compare_evals("logs/baseline.eval", "logs/candidate.eval")
    print(result.summary())

    for r in result.regressions:
        print(f"Sample {r.id} regressed: {r.baseline_score} -> {r.candidate_score}")
"""

from inspect_ai.analysis.comparison._compare import compare_evals
from inspect_ai.analysis.comparison._types import (
    ComparisonResult,
    MetricComparison,
    SampleComparison,
)

__all__ = [
    "compare_evals",
    "ComparisonResult",
    "MetricComparison",
    "SampleComparison",
]
