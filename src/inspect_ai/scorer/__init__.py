from typing import TYPE_CHECKING

from inspect_ai._util.deprecation import relocated_module_attribute
from inspect_ai._util.lazy import lazy_attributes

# eager: type/protocol/metric modules whose own imports do not reach back
# into ``solver`` / ``agent`` / ``log`` implementation code, so importing
# ``inspect_ai.scorer`` cannot trip the cross-package cycle.
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
from ._metrics.std import bootstrap_stderr, std, stderr, var
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
from ._target import Target

if TYPE_CHECKING:
    # lazy: ``Scorer`` and the built-in scorer implementations import
    # ``inspect_ai.solver._task_state`` (and from there ``agent`` / ``model``),
    # so they are loaded on first attribute access via ``lazy_attributes``.
    from ._answer import AnswerPattern, answer
    from ._choice import choice
    from ._classification import exact, f1
    from ._match import includes, match
    from ._math import math
    from ._model import model_graded_fact, model_graded_qa
    from ._multi import multi_scorer
    from ._pattern import pattern
    from ._perplexity import perplexity
    from ._score import score
    from ._scorer import Scorer, scorer
    from ._target_perplexity import target_perplexity

__all__ = [
    "AnswerPattern",
    "CORRECT",
    "INCORRECT",
    "Metric",
    "MetricProtocol",
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
    "answer",
    "at_least",
    "bootstrap_stderr",
    "choice",
    "exact",
    "f1",
    "grouped",
    "includes",
    "match",
    "math",
    "max_score",
    "mean",
    "mean_score",
    "median_score",
    "metric",
    "mode_score",
    "model_graded_fact",
    "model_graded_qa",
    "multi_scorer",
    "pass_at",
    "pattern",
    "perplexity",
    "perplexity_per_seq",
    "perplexity_per_token",
    "score",
    "score_reducer",
    "scorer",
    "std",
    "stderr",
    "target_perplexity",
    "value_to_float",
    "var",
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

lazy_attributes(
    __name__,
    {
        "Scorer": "inspect_ai.scorer._scorer",
        "scorer": "inspect_ai.scorer._scorer",
        "AnswerPattern": "inspect_ai.scorer._answer",
        "answer": "inspect_ai.scorer._answer",
        "choice": "inspect_ai.scorer._choice",
        "exact": "inspect_ai.scorer._classification",
        "f1": "inspect_ai.scorer._classification",
        "includes": "inspect_ai.scorer._match",
        "match": "inspect_ai.scorer._match",
        "math": "inspect_ai.scorer._math",
        "model_graded_fact": "inspect_ai.scorer._model",
        "model_graded_qa": "inspect_ai.scorer._model",
        "multi_scorer": "inspect_ai.scorer._multi",
        "pattern": "inspect_ai.scorer._pattern",
        "perplexity": "inspect_ai.scorer._perplexity",
        "score": "inspect_ai.scorer._score",
        "target_perplexity": "inspect_ai.scorer._target_perplexity",
    },
)
