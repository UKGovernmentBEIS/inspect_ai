from inspect_ai._util.deprecation import relocated_module_attribute

from ._answer import AnswerPattern, answer
from ._choice import choice
from ._classification import exact, f1
from ._match import includes, match
from ._math import math
from ._metric import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    PARTIAL,
    UNCHANGED,
    Metric,
    MetricProtocol,
    SampleScore,
    Score,
    ScoreEdit,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)
from ._metrics.accuracy import accuracy
from ._metrics.grouped import grouped
from ._metrics.mean import mean
from ._metrics.perplexity import perplexity_per_seq, perplexity_per_token
from ._metrics.reliability import (
    McNemarResult,
    MultipleComparison,
    align_paired_scores,
    benjamini_hochberg,
    holm_bonferroni,
    mcnemar_from_scores,
    mcnemar_test,
    min_samples_for_delta,
    paired_delta,
    power_for_samples,
    variance_surface,
)
from ._metrics.std import bootstrap_stderr, std, stderr, var
from ._model import model_graded_fact, model_graded_qa
from ._multi import multi_scorer
from ._pattern import pattern
from ._perplexity import perplexity
from ._reducer import (
    ScoreReducer,
    ScoreReducers,
    at_least,
    max_score,
    mean_score,
    median_score,
    mode_score,
    pass_at,
    pass_k,
    score_reducer,
)
from ._score import score
from ._scorer import Scorer, scorer
from ._target import Target
from ._target_perplexity import target_perplexity

__all__ = [
    "AnswerPattern",
    "CORRECT",
    "INCORRECT",
    "McNemarResult",
    "Metric",
    "MetricProtocol",
    "MultipleComparison",
    "NOANSWER",
    "PARTIAL",
    "SampleScore",
    "Score",
    "ScoreEdit",
    "ScoreReducer",
    "ScoreReducers",
    "Scorer",
    "Target",
    "UNCHANGED",
    "Value",
    "ValueToFloat",
    "accuracy",
    "align_paired_scores",
    "answer",
    "at_least",
    "benjamini_hochberg",
    "bootstrap_stderr",
    "choice",
    "exact",
    "f1",
    "grouped",
    "holm_bonferroni",
    "includes",
    "match",
    "math",
    "max_score",
    "mcnemar_from_scores",
    "mcnemar_test",
    "mean",
    "mean_score",
    "median_score",
    "metric",
    "min_samples_for_delta",
    "mode_score",
    "model_graded_fact",
    "model_graded_qa",
    "multi_scorer",
    "paired_delta",
    "pass_at",
    "pass_k",
    "pattern",
    "perplexity",
    "perplexity_per_seq",
    "perplexity_per_token",
    "power_for_samples",
    "score",
    "score_reducer",
    "scorer",
    "std",
    "stderr",
    "target_perplexity",
    "value_to_float",
    "var",
    "variance_surface",
]
_BOOTSTRAP_RENAME_VERSION = "0.3.58"
_PROVENANCE_DATA_VERSION = "0.3.154"
_REMOVED_IN = "0.4"

relocated_module_attribute(
    "bootstrap_std",
    "inspect_ai.scorer.bootstrap_stderr",
    _BOOTSTRAP_RENAME_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ProvenanceData",
    "inspect_ai.log.ProvenanceData",
    _PROVENANCE_DATA_VERSION,
    _REMOVED_IN,
)
