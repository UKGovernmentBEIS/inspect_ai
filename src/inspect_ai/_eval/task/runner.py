from typing import Any, NotRequired, TypedDict

from openai.types.chat import ChatCompletionMessageParam

# add 'target' and 'scores' to TaskState
# enforce token limit using exceptions
# enforce message limit using exceptions
# create a solver wrapper for this construct
# filesystem: discover this the same way we discover @solver
# sandbox case: if there is a sandbox we copy you to it


class Score(TypedDict):
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


class Sample(TypedDict):
    model: str
    sample_id: str
    epoch: int
    messages: list[ChatCompletionMessageParam]
    metadata: dict[str, Any]
    target: list[str]


class Result(TypedDict):
    output: str
    scores: NotRequired[dict[str, Score]]


async def solver(sample: Sample) -> Result:
    return Result(output="yes")
