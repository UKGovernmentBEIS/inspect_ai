"""Detection and rehydration of categorical (StrEnum) score values.

When a scorer returns ``Score(value=MyEnum.X)`` the enum instance is preserved
in-process (see ``Value`` in ``_metric.py``) but serialises to a plain string.
To make recompute paths (``recompute_metrics``, ``inspect score``) behave
identically to the first run, the category domain is recorded once per scorer
in ``EvalScorer.value_schema`` and used here to reconstruct synthetic
``StrEnum`` instances from the plain strings on reload.
"""

import functools
import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from logging import getLogger
from typing import TYPE_CHECKING, overload

from inspect_ai._util.logger import warn_once

from ._metric import CategoricalSchema, Score, Value, ValueSchema
from ._scorer import unique_scorer_name

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalScorer

logger = getLogger(__name__)


@functools.cache
def _categorical_enum(members: tuple[str, ...]) -> type[StrEnum]:
    """Build (and cache) a synthetic StrEnum with the given members.

    Cached by member tuple so that all rehydrated values from the same domain
    share a single type, which ``_infer_categories`` relies on. Member names
    are positional placeholders; only values are ever observed.
    """
    mapping = {f"M{i}": m for i, m in enumerate(members)}
    return StrEnum("_Categorical", mapping)  # type: ignore[return-value]


def detect_value_schema(
    scores: Sequence[Score],
) -> ValueSchema | dict[str, ValueSchema] | None:
    """Derive a value schema from a scorer's in-process score values.

    Scans all samples so that a stray non-StrEnum first sample (e.g. a parse
    fallback or partially-populated dict) does not suppress the schema.
    """
    scalar: CategoricalSchema | None = None
    per_key: dict[str, ValueSchema] = {}
    saw_dict = False
    for score in scores:
        v = score.value
        if isinstance(v, float) and math.isnan(v):
            continue
        if isinstance(v, StrEnum):
            if scalar is None:
                scalar = CategoricalSchema(categories=[str(m.value) for m in type(v)])
        elif isinstance(v, Mapping):
            saw_dict = True
            for k, val in v.items():
                if k not in per_key and isinstance(val, StrEnum):
                    per_key[k] = CategoricalSchema(
                        categories=[str(m.value) for m in type(val)]
                    )
    if per_key:
        return per_key
    if saw_dict and scalar is None:
        return None
    return scalar


_S = str | int | float | bool


@overload
def _rehydrate_scalar(value: _S, schema: ValueSchema) -> _S: ...
@overload
def _rehydrate_scalar(value: None, schema: ValueSchema) -> None: ...
def _rehydrate_scalar(value: _S | None, schema: ValueSchema) -> _S | None:
    if type(value) is not str or not isinstance(schema, CategoricalSchema):
        return value
    enum = _categorical_enum(tuple(schema.categories))
    try:
        return enum(value)
    except ValueError:
        warn_once(
            logger,
            f"Score value {value!r} is not in the recorded categorical "
            f"domain {schema.categories!r}; leaving as plain string.",
        )
        return value


def rehydrate_value(
    value: Value, schema: ValueSchema | dict[str, ValueSchema]
) -> Value:
    """Reconstruct StrEnum instances in ``value`` according to ``schema``."""
    if isinstance(schema, Mapping):
        if not isinstance(value, Mapping):
            return value
        return {
            k: _rehydrate_scalar(v, schema[k]) if k in schema else v
            for k, v in value.items()
        }
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
        return value
    return _rehydrate_scalar(value, schema)


def value_schemas_by_score_key(
    eval_scorers: "Sequence[EvalScorer]",
) -> dict[str, ValueSchema | dict[str, ValueSchema]]:
    """Map ``sample.scores`` keys to their recorded value schema.

    ``EvalScorer.name`` is the scorer's registry name and need not be unique;
    ``sample.scores`` keys are uniquified via ``unique_scorer_name``. Re-derive
    the unique keys here so duplicated scorer names resolve correctly.
    """
    seen: list[str] = []
    result: dict[str, ValueSchema | dict[str, ValueSchema]] = {}
    for es in eval_scorers:
        key = unique_scorer_name(es.name, seen)
        seen.append(key)
        if es.value_schema is not None:
            result[key] = es.value_schema
    return result
