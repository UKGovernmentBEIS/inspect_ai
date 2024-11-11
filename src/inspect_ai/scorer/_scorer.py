from typing import (
    Any,
    Callable,
    ParamSpec,
    Protocol,
    cast,
    runtime_checkable,
)

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_info,
    registry_name,
    registry_tag,
    registry_unqualified_name,
)
from inspect_ai.solver._task_state import TaskState

from ._metric import Metric, Score
from ._target import Target


@runtime_checkable
class Scorer(Protocol):
    r"""Score model outputs.

    Evaluate the passed outputs and targets and return a
    dictionary with scoring outcomes and context.

    Args:
        state (TaskState): Task state
        target (Target): Ideal target for the output.
    """

    async def __call__(
        self,
        state: TaskState,
        target: Target,
    ) -> Score: ...


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
    return cast(Scorer, registry_create("scorer", name, **kwargs))


def scorer(
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]],
    name: str | None = None,
    **metadata: Any,
) -> Callable[[Callable[P, Scorer]], Callable[P, Scorer]]:
    r"""Decorator for registering scorers.

    Args:
        metrics (list[Metric] | dict[str, list[Metric]]): One or more metrics to calculate
            over the scores.
        name (str | None):
            Optional name for scorer. If the decorator has no name
            argument then the name of the underlying ScorerType
            object will be used to automatically assign a name.
        **metadata (dict[str,Any]): Additional values to serialize
            in metadata.

    Returns:
        Scorer with registry attributes.

    """

    def wrapper(scorer_type: Callable[P, Scorer]) -> Callable[P, Scorer]:
        # determine the name (explicit or implicit from object)
        scorer_name = registry_name(
            scorer_type, name if name else getattr(scorer_type, "__name__")
        )

        # wrap instantiations of scorer so they carry registry info and metrics
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


def scorer_metrics(
    scorer: Scorer,
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]]:
    metrics_raw = registry_info(scorer).metadata[SCORER_METRICS]
    if isinstance(metrics_raw, dict):
        return cast(dict[str, list[Metric]], metrics_raw)
    else:
        return cast(list[Metric | dict[str, list[Metric]]], metrics_raw)


def unique_scorer_name(scorer: Scorer, already_used_names: list[str]) -> str:
    base_name = registry_unqualified_name(scorer)
    scorer_name = base_name
    count = 1
    while scorer_name in already_used_names:
        scorer_name = f"{base_name}{count}"
        count = count + 1
    return scorer_name


SCORER_METRICS = "metrics"
