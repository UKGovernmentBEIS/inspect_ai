from typing import Any, Awaitable, Callable

from jsonschema import Draft7Validator
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import to_json

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.log._samples import sample_active
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._providers.providers import validate_openai_client


@agent
def bridge(agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> Agent:
    """Bridge an external agent into an Inspect Agent.

    See documentation at <https://inspect.aisi.org.uk/agent-bridge.html>

    Args:
      agent: Callable which takes a sample `dict` and returns a result `dict`.

    Returns:
      Standard Inspect solver.
    """
    validate_openai_client("Agent bridge()")

    from openai.types.chat import ChatCompletionMessageParam

    from inspect_ai.model._openai import (
        chat_messages_from_openai,
        openai_chat_messages,
    )

    from .patch import openai_request_to_inspect_model

    class BridgeInput(BaseModel):
        messages: list[ChatCompletionMessageParam]

        # here for backward compatibilty w/ previous bridge
        # (we may choose to add this to AgentState at some point)
        metadata: dict[str, Any]

        # temporarily here for backward compatibility w/ previous bridge
        input: list[ChatCompletionMessageParam]

    class BridgeResult(BaseModel):
        output: str
        messages: list[ChatCompletionMessageParam] | None = Field(default=None)

    result_schema = BridgeResult.model_json_schema()
    result_validator = Draft7Validator(result_schema)

    # validate that the agent is an async function
    if not is_callable_coroutine(agent):
        raise TypeError(f"'{agent.__name__}' is not declared as an async callable.")

    async def execute(state: AgentState) -> AgentState:
        # create input (use standard gpt-4 message encoding -- i.e. no 'developer' messages)
        sample = sample_active()
        metadata = (sample.sample.metadata if sample is not None else None) or {}
        messages = await openai_chat_messages(state.messages)
        input = BridgeInput(messages=messages, metadata=metadata, input=messages)

        # run target function
        async with openai_request_to_inspect_model():
            # call the function
            result_dict = await agent(input.model_dump())
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
        state.output = ModelOutput.from_content(
            model=get_model().name, content=result.output
        )
        if result.messages is not None:
            state.messages = chat_messages_from_openai(
                state.output.model, result.messages
            )

        return state

    return execute
