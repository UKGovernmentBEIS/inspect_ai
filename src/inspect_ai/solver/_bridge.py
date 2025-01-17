from os import PathLike
from typing import Any, Awaitable, Callable, Literal, NotRequired, TypedDict, overload

from openai.types.chat import ChatCompletionMessageParam

from ._solver import Generate, Solver
from ._task_state import TaskState


class ScoreDict(TypedDict):
    value: (
        str
        | int
        | float
        | bool
        | list[str | int | float | bool]
        | dict[str, str | int | float | bool]
    )
    answer: NotRequired[str]
    explanation: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]


class SampleDict(TypedDict):
    model: str
    sample_id: str
    epoch: int
    messages: list[ChatCompletionMessageParam]
    metadata: dict[str, Any]
    target: list[str]


class ResultDict(TypedDict):
    output: str
    scores: NotRequired[dict[str, ScoreDict]]


@overload
def bridge(target: Callable[[SampleDict], Awaitable[ResultDict]]) -> Solver: ...


@overload
def bridge(
    target: PathLike[str],
    args: dict[str, Any],
    sandbox: bool | Literal["auto"] = "auto",
) -> Solver: ...


def bridge(
    target: Callable[[SampleDict], Awaitable[ResultDict]] | PathLike[str],
    args: dict[str, Any] | None = None,
    sandbox: bool | Literal["auto"] = "auto",
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve
