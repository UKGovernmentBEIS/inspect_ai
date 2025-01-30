from typing import Any, Awaitable, Callable

from jsonschema import Draft7Validator
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import to_json

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.scorer._metric import Score

from .._solver import Generate, Solver, solver
from .._task_state import TaskState


@solver
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Solver:
    """Bridge an external agent into an Inspect Solver.

    See documentation at https://inspect.ai-safety-institute.org.uk/agent-bridge.html

    Args:
      agent: Callable which takes a sample `dict` and returns a result `dict`.

    Returns:
      Standard Inspect solver.
    """
    validate_openai_client("Solver bridge()")

    from openai.types.chat import ChatCompletionMessageParam

    from inspect_ai.model._openai import (
        chat_messages_from_openai,
        openai_chat_messages,
    )

    from .patch import openai_request_to_inspect_model

    class BridgeSample(BaseModel):
        sample_id: str
        epoch: int
        input: list[ChatCompletionMessageParam]
        metadata: dict[str, Any]
        target: list[str]

    class BridgeResult(BaseModel):
        output: str
        messages: list[ChatCompletionMessageParam] | None = Field(default=None)
        scores: dict[str, Score] | None = Field(default=None)

    result_schema = BridgeResult.model_json_schema()
    result_validator = Draft7Validator(result_schema)

    # validate that the agent is an async function
    if not is_callable_coroutine(agent):
        raise TypeError(f"'{agent.__name__}' is not declared as an async callable.")

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # resolve input to array
        input: list[ChatMessage] = (
            [ChatMessageUser(content=state.input)]
            if isinstance(state.input, str)
            else state.input
        )

        # create sample
        sample = BridgeSample(
            sample_id=str(state.sample_id),
            epoch=state.epoch,
            input=await openai_chat_messages(input, state.model.name),
            metadata=state.metadata,
            target=list(state.target),
        )

        # run target function
        async with openai_request_to_inspect_model():
            # call the function
            result_dict = await agent(sample.model_dump())
            try:
                result = BridgeResult.model_validate(result_dict)
            except ValidationError:
                # if we fail to validate provide a better human readable error
                errors = list(result_validator.iter_errors(result_dict))
                message = "\n".join(
                    ["Result returned from bridged solver is not valid:"]
                    + [f" - {error.message}" for error in errors]
                    + ["", to_json(result_dict, indent=2).decode()]
                )
                raise ValueError(message)

        # update and return state
        state.output.completion = result.output
        if result.messages is not None:
            state.messages = chat_messages_from_openai(result.messages)
        if result.scores is not None:
            state.scores = result.scores

        return state

    return solve
