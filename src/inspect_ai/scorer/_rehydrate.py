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
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from logging import getLogger
from typing import overload

from inspect_ai._util.logger import warn_once
from inspect_ai.log._log import CategoricalSchema, EvalScorer, ValueSchema

from ._metric import Score, Value
from ._scorer import unique_scorer_name

logger = getLogger(__name__)


_MEMBER_NAME_INVALID = re.compile(r"[^A-Za-z0-9_]")


def _member_name(value: str, idx: int) -> str:
    name = _MEMBER_NAME_INVALID.sub("_", value).upper()
    if not name or not name[0].isalpha():
        name = f"M{idx}_{name}" if name else f"M{idx}"
    return name


@functools.cache
def _categorical_enum(members: tuple[str, ...]) -> type[StrEnum]:
    """Build (and cache) a synthetic StrEnum with the given members.

    Cached by member tuple so that all rehydrated values from the same domain
    share a single type, which ``_infer_categories`` relies on.
    """
    mapping = {_member_name(m, i): m for i, m in enumerate(members)}
    return StrEnum("_Categorical", mapping)  # type: ignore[return-value]


def detect_value_schema(
    scores: Sequence[Score],
) -> ValueSchema | dict[str, ValueSchema] | None:
    """Derive a value schema from a scorer's in-process score values."""
    for score in scores:
        v = score.value
        if isinstance(v, float) and math.isnan(v):
            continue
        if isinstance(v, StrEnum):
            return CategoricalSchema(categories=[str(m.value) for m in type(v)])
        if isinstance(v, Mapping):
            per_key = {
                k: CategoricalSchema(categories=[str(m.value) for m in type(val)])
                for k, val in v.items()
                if isinstance(val, StrEnum)
            }
            return per_key or None
        return None
    return None


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
    eval_scorers: Sequence[EvalScorer],
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
