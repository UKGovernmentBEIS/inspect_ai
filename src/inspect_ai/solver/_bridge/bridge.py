from typing import Any, Awaitable, Callable, NotRequired, TypedDict

from openai.types.chat import ChatCompletionMessageParam

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._openai import (
    chat_messages_from_openai,
    openai_chat_messages,
)
from inspect_ai.scorer._metric import Score

from .._solver import Generate, Solver, solver
from .._task_state import TaskState
from .patch import openai_request_to_inspect_model


class SampleDict(TypedDict):
    model: str
    sample_id: str
    epoch: int
    messages: list[ChatCompletionMessageParam]
    metadata: dict[str, Any]
    target: list[str]


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


class ResultDict(TypedDict):
    output: str
    messages: NotRequired[list[ChatCompletionMessageParam]]
    scores: NotRequired[dict[str, ScoreDict]]


@solver
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Solver:
    """Bridge an external agent into an Inspect Solver.

    Integrate an external agent with no Inspect dependencies by converting
    it to a Solver. The only requirements of the agent are that it use
    the standard OpenAI API and that it consume and produce `dict` values
    as described below. While the agent function calls the standard
    OpenAI API, these calls are intercepted by Inspect and sent to the
    requisite Inspect model provider.

    Here is the type contract for bridged solvers (you don't need to use
    or import these types in your agent, your `dict` usage should
    just conform to the protocol):

    ```python
    from openai.types.chat import ChatCompletionMessageParam

    class SampleDict(TypedDict):
        model: str
        sample_id: str
        epoch: int
        messages: list[ChatCompletionMessageParam]
        metadata: dict[str, Any]
        target: list[str]

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

    class ResultDict(TypedDict):
        output: str
        messages: NotRequired[list[ChatCompletionMessageParam]]
        scores: NotRequired[dict[str, ScoreDict]]

    async def agent(sample: SampleDict) -> ResultDict: ...
    ```

    The agent function must be async, and should accept and return
    `dict` values as-per the type declarations (you aren't required
    to use these types exactly (they merely document the requirements)
    so long as you consume and produce `dict` values that match
    their declarations.

    Returning `messages` is not required but is highly recommended
    so that people running the agent can see the full message history
    in the Inspect log viewer.

    Returning `scores` is entirely optional (most agents
    will in fact rely on Inspect native scorers, this is here as an
    escape hatch for agents that want to do their own scoring).


    Here is the simplest possible agent definition:

    ```python
    from openai import AsyncOpenAI

    async def my_agent(sample: dict[str, Any]) -> dict[str, Any]:
        client = AsyncOpenAI()
        completion = await client.chat.completions.create(
            messages=sample["messages"],
            model=sample["model"]
        )
        return {
            "output": completion.choices[0].message.content
        }
    ```

    Note that you should always pass the "model" along to OpenAI exactly
    as passed in the sample. While you are calling the standard
    OpenAI API, these calls are intercepted by Inspect and sent to the
    requisite Inspect model provider.

    Here is how you can use the `bridge()` function to use this agent
    as a solver:

    ```python
    from inspect_ai import Task, task
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import includes
    from inspect_ai.solver import bridge

    from agents import my_agent

    @task
    def hello():
        return Task(
            dataset=[Sample(input="Please print the word 'hello'?", target="hello")],
            solver=bridge(my_agent),
            scorer=includes(),
        )
    ```
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # convert messages to openai messages
        input: list[ChatMessage] = (
            [ChatMessageUser(content=state.input)]
            if isinstance(state.input, str)
            else state.input
        )
        messages = await openai_chat_messages(input, state.model.name)

        # create sample
        sample = dict(
            model=str(state.model),
            sample_id=str(state.sample_id),
            epoch=state.epoch,
            messages=messages,
            metadata=state.metadata,
            target=list(state.target),
        )

        # run target function
        async with openai_request_to_inspect_model():
            result = await agent(sample)

        # update and return state
        state.output.completion = result["output"]
        if "messages" in result:
            state.messages = chat_messages_from_openai(result["messages"])
        if "scores" in result:
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
