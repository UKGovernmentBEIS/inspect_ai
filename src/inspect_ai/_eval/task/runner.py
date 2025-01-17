from typing import Any, Awaitable, Callable, NotRequired, TypedDict

from openai.types.chat import ChatCompletionMessageParam


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


BridgedSolver = Callable[[SampleDict], Awaitable[ResultDict]]
