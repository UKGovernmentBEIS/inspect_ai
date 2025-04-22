from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
from typing import (
    Any,
    Callable,
    ParamSpec,
    Protocol,
    cast,
    runtime_checkable,
)

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_create,
    registry_info,
    registry_name,
    registry_params,
    registry_tag,
    registry_unqualified_name,
)
from inspect_ai.solver._task_state import TaskState

from ._metric import Metric, MetricSpec, Score, as_metric_spec
from ._target import Target


@runtime_checkable
class Scorer(Protocol):
    async def __call__(
        self,
        state: TaskState,
        target: Target,
    ) -> Score:
        r"""Score model outputs.

        Evaluate the passed outputs and targets and return a
        dictionary with scoring outcomes and context.

        Args:
            state: Task state
            target: Ideal target for the output.

        Examples:
          ```python
          @scorer
          def custom_scorer() -> Scorer:
              async def score(state: TaskState, target: Target) -> Score:
                  # Compare state / model output with target
                  # to yield a score
                  return Score(value=...)

              return score
          ````
        """
        ...


@dataclass(frozen=True)
class ScorerSpec:
    """Scorer specification used to (re-)create scorers."""

    scorer: str
    """Scorer name"""

    args: dict[str, Any] = field(default_factory=dict)
    """Scorer arguments."""

    metadata: dict[str, Any] | None = field(default=None)
    """Scorer metadata"""

    metrics: (
        list[MetricSpec | dict[str, list[MetricSpec]]]
        | dict[str, list[MetricSpec]]
        | None
    ) = field(default=None)
    """Scorer metrics"""


P = ParamSpec("P")


def scorer_register(
    scorer: Callable[P, Scorer], name: str = "", metadata: dict[str, Any] = {}
) -> Callable[P, Scorer]:
    r"""Register a function or class as a scorer.

    Args:
        scorer (ScorerType):
            Scorer, function that returns a Scorer, or class
            deriving from the Scorer protocol.
        name (str): Name of scorer (Optional, defaults to object name)
        metadata (dict[str,Any]): Additional values to serialize
            in metadata.

    Returns:
        Scorer with registry attributes.
    """
    scorer_name = name if name else getattr(scorer, "__name__")
    registry_add(
        scorer, RegistryInfo(type="scorer", name=scorer_name, metadata=metadata)
    )
    return scorer


def scorer_create(name: str, **kwargs: Any) -> Scorer:
    r"""Create a Scorer based on its registered name.

    Args:
        name (str): Name of scorer (Optional, defaults to object name)
        **kwargs (dict): Optional creation arguments for the scorer

    Returns:
        Scorer with registry info attribute
    """
    return registry_create("scorer", name, **kwargs)


def scorer(
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]],
    name: str | None = None,
    **metadata: Any,
) -> Callable[[Callable[P, Scorer]], Callable[P, Scorer]]:
    r"""Decorator for registering scorers.

    Args:
        metrics: One or more metrics to calculate
            over the scores.
        name: Optional name for scorer. If the decorator has no name
            argument then the name of the underlying ScorerType
            object will be used to automatically assign a name.
        **metadata: Additional values to serialize
            in metadata.

    Returns:
        Scorer with registry attributes.

    Examples:
      ```python
      @scorer
      def custom_scorer() -> Scorer:
          async def score(state: TaskState, target: Target) -> Score:
              # Compare state / model output with target
              # to yield a score
              return Score(value=...)

          return score
      ````
    """

    def wrapper(scorer_type: Callable[P, Scorer]) -> Callable[P, Scorer]:
        # determine the name (explicit or implicit from object)
        scorer_name = registry_name(
            scorer_type, name if name else getattr(scorer_type, "__name__")
        )

        # wrap instantiations of scorer so they carry registry info and metrics
        @wraps(scorer_type)
        def scorer_wrapper(*args: P.args, **kwargs: P.kwargs) -> Scorer:
            scorer = scorer_type(*args, **kwargs)

            if not is_callable_coroutine(scorer):
                raise TypeError(
                    f"'{scorer_name}' is not declared as an async callable."
                )

            registry_tag(
                scorer_type,
                scorer,
                RegistryInfo(
                    type="scorer",
                    name=scorer_name,
                    metadata={SCORER_METRICS: metrics} | metadata,
                ),
                *args,
                **kwargs,
            )
            return scorer

        # register the scorer
        return scorer_register(
            scorer=cast(Callable[P, Scorer], scorer_wrapper),
            name=scorer_name,
            metadata={SCORER_METRICS: metrics} | metadata,
        )

    return wrapper


def as_scorer_spec(scorer: Scorer) -> ScorerSpec:
    if not is_registry_object(scorer):
        raise PrerequisiteError(
            f"The scorer {getattr(scorer, '__name__', '<unknown>')} was not created by a function decorated with @scorer so cannot be recorded."
        )
    name = registry_unqualified_name(scorer)
    metrics = scorer_metrics(scorer)
    resolved_metrics = resolve_metrics(metrics)

    args = registry_params(scorer)
    metadata = deepcopy(registry_info(scorer).metadata)
    del metadata[SCORER_METRICS]

    return ScorerSpec(
        scorer=name, args=args, metadata=metadata, metrics=resolved_metrics
    )


def resolve_metrics(
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]],
) -> (
    list[MetricSpec | dict[str, list[MetricSpec]]] | dict[str, list[MetricSpec]] | None
):
    if isinstance(metrics, list):
        resolved_metrics: list[MetricSpec | dict[str, list[MetricSpec]]] = []
        for metric_item in metrics:
            if isinstance(metric_item, Metric):
                resolved_metrics.append(as_metric_spec(metric_item))
            else:
                resolved_metrics.append(
                    {
                        metric_group: [
                            as_metric_spec(metric) for metric in metrics_list
                        ]
                        for metric_group, metrics_list in metric_item.items()
                    }
                )
        return resolved_metrics
    else:
        return {
            metric_group: [as_metric_spec(metric) for metric in metrics_list]
            for metric_group, metrics_list in metrics.items()
        }


def scorer_metrics(
    scorer: Scorer,
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]]:
    metrics_raw = registry_info(scorer).metadata[SCORER_METRICS]
    if isinstance(metrics_raw, dict):
        return cast(dict[str, list[Metric]], metrics_raw)
    else:
        return cast(list[Metric | dict[str, list[Metric]]], metrics_raw)


def unique_scorer_name(scorer: Scorer | str, already_used_names: list[str]) -> str:
    base_name = scorer if isinstance(scorer, str) else registry_unqualified_name(scorer)
    scorer_name = base_name
    count = 1
    while scorer_name in already_used_names:
        scorer_name = f"{base_name}{count}"
        count = count + 1
    return scorer_name


SCORER_METRICS = "metrics"
