import contextlib
import re
from contextvars import ContextVar
from functools import wraps
from time import time
from typing import Any, AsyncGenerator, Type, cast

from openai._base_client import AsyncAPIClient, _AsyncStreamT
from openai._models import FinalRequestOptions
from openai._types import ResponseT
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolParam,
)
from shortuuid import uuid

from inspect_ai.model._generate_config import GenerateConfig, ResponseSchema
from inspect_ai.model._model import get_model
from inspect_ai.model._openai import (
    chat_messages_from_openai,
    openai_chat_choices,
    openai_completion_usage,
)
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema


@contextlib.asynccontextmanager
async def openai_request_to_inspect_model() -> AsyncGenerator[None, None]:
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
    if not _patch_initialised:
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
                    return await inspect_model_request(model_name, options)

            # otherwise just delegate
            return await original_request(
                self,
                cast_to,
                options,
                stream=stream,
                stream_cls=stream_cls,
            )

        setattr(AsyncAPIClient, "request", patched_request)


async def inspect_model_request(
    model_name: str, options: FinalRequestOptions
) -> ChatCompletion:
    from inspect_ai.solver._task_state import sample_state

    # resolve model
    if model_name == "inspect":
        model = get_model()
    else:
        model = get_model(model_name.removeprefix("inspect/"))

    # convert openai messages to inspect messages
    json_data = cast(dict[str, Any], options.json_data)
    messages: list[ChatCompletionMessageParam] = json_data["messages"]
    input = chat_messages_from_openai(model.api.model_name, messages)

    # convert openai tools to inspect tools
    tools: list[ChatCompletionToolParam] = json_data.get("tools", [])
    inspect_tools: list[ToolInfo] = []
    for tool in tools:
        function = tool["function"].copy()
        inspect_tools.append(
            ToolInfo(
                name=function["name"],
                description=function["description"],
                parameters=ToolParams.model_validate(function["parameters"]),
            )
        )

    # convert openai tool choice to inspect tool_choice
    inspect_tool_choice: ToolChoice | None = None
    tool_choice: ChatCompletionToolChoiceOptionParam | None = json_data.get(
        "tool_choice", None
    )
    if tool_choice is not None:
        match tool_choice:
            case "auto" | "none":
                inspect_tool_choice = tool_choice
            case "required":
                inspect_tool_choice = "any"
            case _:
                inspect_tool_choice = ToolFunction(name=tool_choice["function"]["name"])

    output = await model.generate(
        input=input,
        tools=inspect_tools,
        tool_choice=inspect_tool_choice,
        config=generate_config_from_openai(options),
    )

    # if we are using the "default" inspect model for the task, update state.messages
    if model_name == "inspect":
        state = sample_state()
        if state:
            state.messages = input + [output.choices[0].message]

    # inspect completion to openai completion
    return ChatCompletion(
        id=uuid(),
        created=int(time()),
        object="chat.completion",
        choices=openai_chat_choices(output.choices),
        model=model_name,
        usage=openai_completion_usage(output.usage) if output.usage else None,
    )


def generate_config_from_openai(options: FinalRequestOptions) -> GenerateConfig:
    # get options dict
    json_data = cast(dict[str, Any], options.json_data)

    config = GenerateConfig()
    config.max_tokens = json_data.get(
        "max_completion_tokens", json_data.get("max_tokens", None)
    )
    config.top_p = json_data.get("top_p", None)
    config.temperature = json_data.get("temperature", None)
    stop = json_data.get("stop", None)
    if stop:
        config.stop_seqs = [stop] if isinstance(stop, str) else stop
    config.frequency_penalty = json_data.get("frequency_penalty", None)
    config.presence_penalty = json_data.get("presence_penalty", None)
    config.seed = json_data.get("seed", None)
    config.num_choices = json_data.get("n", None)
    config.logprobs = json_data.get("logprobs", None)
    config.top_logprobs = json_data.get("top_logprobs", None)
    config.logit_bias = json_data.get("logit_bias", None)
    config.parallel_tool_calls = json_data.get("parallel_tool_calls", None)
    config.reasoning_effort = json_data.get("reasoning_effort", None)

    # response format
    response_format: dict[str, Any] | None = json_data.get("response_format", None)
    if response_format is not None:
        json_schema: dict[str, Any] | None = response_format.get("json_schema", None)
        if json_schema is not None:
            config.response_schema = ResponseSchema(
                name=json_schema.get("name", "schema"),
                description=json_schema.get("description", None),
                json_schema=JSONSchema.model_validate(json_schema.get("schema", {})),
                strict=json_schema.get("strict", None),
            )

    return config
