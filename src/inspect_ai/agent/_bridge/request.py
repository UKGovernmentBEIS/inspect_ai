from time import time
from typing import Any

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolParam,
)
from shortuuid import uuid

from inspect_ai.model._generate_config import GenerateConfig, ResponseSchema
from inspect_ai.model._model import get_model, model_roles
from inspect_ai.model._openai import (
    messages_from_openai,
    openai_chat_choices,
    openai_completion_usage,
)
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema


async def inspect_model_request(json_data: dict[str, Any]) -> ChatCompletion:
    # resolve model and model name
    model_name = str(json_data["model"])
    if model_name == "inspect":
        model = get_model()
    else:
        model_name = model_name.removeprefix("inspect/")
        if model_name in model_roles():
            model = get_model(role=model_name)
        else:
            model = get_model(model_name)
    model_name = model.api.model_name

    # convert openai messages to inspect messages
    messages: list[ChatCompletionMessageParam] = json_data["messages"]
    input = await messages_from_openai(messages, model.api.model_name)

    # convert openai tools to inspect tools
    tools: list[ChatCompletionToolParam] = json_data.get("tools", [])
    inspect_tools: list[ToolInfo] = []
    for tool in tools:
        assert tool["type"] == "function", '"custom" tool calls are not supported'
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
                assert tool_choice["type"] == "function", (
                    '"custom" tool calls are not supported'
                )
                inspect_tool_choice = ToolFunction(name=tool_choice["function"]["name"])

    output = await model.generate(
        input=input,
        tools=inspect_tools,
        tool_choice=inspect_tool_choice,
        config=generate_config_from_openai(json_data),
    )

    # inspect completion to openai completion
    return ChatCompletion(
        id=uuid(),
        created=int(time()),
        object="chat.completion",
        choices=openai_chat_choices(output.choices),
        model=model_name,
        usage=openai_completion_usage(output.usage) if output.usage else None,
    )


def generate_config_from_openai(json_data: dict[str, Any]) -> GenerateConfig:
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
