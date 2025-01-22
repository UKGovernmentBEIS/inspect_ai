from typing import Any, Awaitable, Callable, NotRequired, TypedDict

from openai.types.chat import ChatCompletionMessageParam

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._openai import (
    chat_messages_from_openai,
    openai_chat_messages,
)
from inspect_ai.scorer._metric import Score

from .._solver import Generate, Solver
from .._task_state import TaskState
from .patch import openai_request_to_inspect_model


class ScoreDict(TypedDict):
    value: (
        str
        | int
        | float
        | bool
        | list[str | int | float | bool]
        | dict[str, str | int | float | bool | None]
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
    messages: NotRequired[list[ChatCompletionMessageParam]]
    scores: NotRequired[dict[str, ScoreDict]]


def bridge(target: Callable[[SampleDict], Awaitable[ResultDict]]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # convert messages to openai messages
        input: list[ChatMessage] = (
            [ChatMessageUser(content=state.input)]
            if isinstance(state.input, str)
            else state.input
        )
        messages = await openai_chat_messages(input, state.model.name)

        # create sample
        sample = SampleDict(
            model=str(state.model),
            sample_id=str(state.sample_id),
            epoch=state.epoch,
            messages=messages,
            metadata=state.metadata,
            target=list(state.target),
        )

        # run target function
        async with openai_request_to_inspect_model():
            result = await target(sample)

        # update and return state
        state.output.completion = result["output"]
        if result["messages"]:
            state.messages = chat_messages_from_openai(result["messages"])
        if result["scores"]:
            state.scores = {
                k: Score(
                    value=v["value"],
                    answer=v["answer"],
                    explanation=v["explanation"],
                    metadata=v["metadata"],
                )
                for k, v in result["scores"].items()
            }

        return state

    return solve
