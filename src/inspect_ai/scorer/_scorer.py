from typing import (
    Any,
    Callable,
    Protocol,
    Sequence,
    TypeVar,
    Union,
    cast,
    overload,
    runtime_checkable,
)

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_info,
    registry_name,
    registry_tag,
)
from inspect_ai.solver import TaskState

from ._metric import Metric, Score


class Target(Sequence[str]):
    """Target for scoring.

    Target is a sequence of one or more strings. Use the
    `text` property to access the value as a single string.
    """

    def __init__(self, target: str | list[str]) -> None:
        self.target = target if isinstance(target, list) else [target]

    @overload
    def __getitem__(self, index: int) -> str:
        ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[str]:
        ...

    def __getitem__(self, index: Union[int, slice]) -> Union[str, Sequence[str]]:
        return self.target[index]

    def __len__(self) -> int:
        return len(self.target)

    @property
    def text(self) -> str:
        return "".join(self.target)


@runtime_checkable
class Scorer(Protocol):
    r"""Score model outputs.

    Evaluate the passed outputs and targets and return a
    dictionary with scoring outcomes and context.

    Args:
        state (TaskState): Task state
        target (Target): Ideal target for the output.
    """

    async def __call__(self, state: TaskState, target: Target) -> Score:
        ...


ScorerType = TypeVar("ScorerType", Callable[..., Scorer], type[Scorer])
r"""Scorer type.

Valid scorer types include:
 - Functions that return a Scorer
 - Classes derivied from Scorer
"""


def scorer_register(scorer: ScorerType, name: str = "") -> ScorerType:
    r"""Register a function or class as a scorer.

    Args:
        scorer (ScorerType):
            Scorer, function that returns a Scorer, or class
            deriving from the Scorer protocol.
        name (str): Name of scorer (Optional, defaults to object name)

    Returns:
        Scorer with registry attributes.
    """
    scorer_name = (name if name else getattr(scorer, "__name__")).lower()
    registry_add(scorer, RegistryInfo(type="scorer", name=scorer_name))
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
    metrics: list[Metric], name: str | None = None, **metadata: Any
) -> Callable[[Callable[..., Scorer]], Callable[..., Scorer]]:
    r"""Decorator for registering scorers.

    Args:
        metrics (list[Metric]): One or more metrics to calculate
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

    def wrapper(scorer_type: ScorerType) -> ScorerType:
        # determine the name (explicit or implicit from object)
        scorer_name = registry_name(
            scorer_type, name if name else getattr(scorer_type, "__name__")
        )

        # wrap instatiations of scorer so they carry registry info and metrics
        def scorer_wrapper(*args: Any, **kwargs: Any) -> Scorer:
            scorer = scorer_type(*args, **kwargs)

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
        return scorer_register(cast(ScorerType, scorer_wrapper), scorer_name)

    return wrapper


def scorer_metrics(scorer: Scorer) -> list[Metric]:
    return cast(list[Metric], registry_info(scorer).metadata[SCORER_METRICS])


SCORER_METRICS = "metrics"
