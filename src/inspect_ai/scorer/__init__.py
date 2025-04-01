from inspect_ai._util.deprecation import relocated_module_attribute

from ._answer import AnswerPattern, answer
from ._choice import choice
from ._classification import exact, f1
from ._match import includes, match
from ._metric import (
    CORRECT,
    INCORRECT,
    NOANSWER,
    PARTIAL,
    Metric,
    MetricProtocol,
    SampleScore,
    Score,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)
from ._metrics.accuracy import accuracy
from ._metrics.grouped import grouped
from ._metrics.mean import mean
from ._metrics.std import bootstrap_stderr, std, stderr, var
from ._model import model_graded_fact, model_graded_qa
from ._multi import multi_scorer
from ._pattern import pattern
from ._reducer import (
    ScoreReducer,
    ScoreReducers,
    at_least,
    max_score,
    mean_score,
    median_score,
    mode_score,
    pass_at,
    score_reducer,
)
from ._score import score
from ._scorer import Scorer, scorer
from ._target import Target

__all__ = [
    "includes",
    "match",
    "model_graded_qa",
    "model_graded_fact",
    "answer",
    "choice",
    "pattern",
    "f1",
    "exact",
    "AnswerPattern",
    "Scorer",
    "Target",
    "scorer",
    "accuracy",
    "bootstrap_stderr",
    "std",
    "stderr",
    "mean",
    "grouped",
    "var",
    "Metric",
    "MetricProtocol",
    "metric",
    "Score",
    "SampleScore",
    "score",
    "Value",
    "ValueToFloat",
    "value_to_float",
    "CORRECT",
    "INCORRECT",
    "PARTIAL",
    "NOANSWER",
    "multi_scorer",
    "ScoreReducer",
    "ScoreReducers",
    "score_reducer",
    "mode_score",
    "mean_score",
    "median_score",
    "max_score",
    "at_least",
    "pass_at",
]
_BOOTSTRAP_RENAME_VERSION = "0.3.58"
_REMOVED_IN = "0.4"

relocated_module_attribute(
    "bootstrap_std",
    "inspect_ai.scorer.bootstrap_stderr",
    _BOOTSTRAP_RENAME_VERSION,
    _REMOVED_IN,
)
