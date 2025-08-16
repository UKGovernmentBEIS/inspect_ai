import contextlib
import re
from contextvars import ContextVar
from functools import wraps
from typing import Any, AsyncGenerator, Awaitable, Callable, Type, cast

from jsonschema import Draft7Validator
from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import to_json

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._bridge.request import inspect_model_request
from inspect_ai.log._samples import sample_active
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._openai import (
    messages_from_openai,
    messages_to_openai,
)
from inspect_ai.model._providers.providers import validate_openai_client


@contextlib.asynccontextmanager
async def agent_bridge() -> AsyncGenerator[None, None]:
    """Agent bridge.

    ::: callout-note
    The `agent_bridge()` function is available only in the development version of Inspect. To install the development version from GitHub:

    ``` bash
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
    ```
    :::

    Provide Inspect integration for 3rd party agents that use the
    OpenAI Completions API. The bridge patches the OpenAI client
    library to redirect any model named "inspect" (or prefaced with
    "inspect/" for non-default models) into the Inspect model API.

    See the [Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html)
    documentation for additional details.
    """
    # ensure one time init
    init_openai_request_patch()

    # set the patch enabled for this context and child coroutines
    token = _patch_enabled.set(True)
    try:
        yield
    finally:
        _patch_enabled.reset(token)


_patch_initialised: bool = False

_patch_enabled: ContextVar[bool] = ContextVar(
    "openai_request_patch_enabled", default=False
)


def init_openai_request_patch() -> None:
    global _patch_initialised
    if _patch_initialised:
        return

    # get reference to original method
    original_request = getattr(AsyncAPIClient, "request")
    if original_request is None:
        raise RuntimeError("Couldn't find 'request' method on AsyncAPIClient")

    @wraps(original_request)
    async def patched_request(
        self: AsyncAPIClient,
        cast_to: Type[ResponseT],
        options: FinalRequestOptions,
        *,
        stream: bool = False,
        stream_cls: type[_AsyncStreamT] | None = None,
    ) -> Any:
        # we have patched the underlying request method so now need to figure out when to
        # patch and when to stand down
        if (
            # enabled for this coroutine
            _patch_enabled.get()
            # completions request
            and options.url == "/chat/completions"
        ):
            # must also be an explicit request for an inspect model
            json_data = cast(dict[str, Any], options.json_data)
            model_name = str(json_data["model"])
            if re.match(r"^inspect/?", model_name):
                return await inspect_model_request(json_data)

        # otherwise just delegate
        return await original_request(
            self,
            cast_to,
            options,
            stream=stream,
            stream_cls=stream_cls,
        )

    setattr(AsyncAPIClient, "request", patched_request)
    _patch_initialised = True


@agent
def bridge(
    agent: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> Agent:
    """Bridge an external agent into an Inspect Agent.

    ::: callout-note
    Note that this function is deprecated in favor of the `agent_bridge()`
    function. If you are creating a new agent bridge we recommend you use this function rather than `bridge()`.

    If you do choose to use the `bridge()` function, these [examples](https://github.com/UKGovernmentBEIS/inspect_ai/tree/b4670e798dc8d9ff379d4da4ef469be2468d916f/examples/bridge) demostrate its basic usage.
    :::

    Args:
      agent: Callable which takes a sample `dict` and returns a result `dict`.

    Returns:
      Inspect agent.
    """
    validate_openai_client("Agent bridge()")

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
        messages = await messages_to_openai(state.messages)
        input = BridgeInput(messages=messages, metadata=metadata, input=messages)

        # run target function with patch applied
        async with agent_bridge():
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
            state.messages = await messages_from_openai(
                result.messages, state.output.model
            )

        return state

    return execute
