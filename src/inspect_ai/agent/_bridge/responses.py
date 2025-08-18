from logging import getLogger
from time import time
from typing import Any

from openai.types.responses import Response, ResponseInputItemParam, ToolParam
from openai.types.responses.response_create_params import (
    ToolChoice as ResponsesToolChoice,
)
from shortuuid import uuid

from inspect_ai._util.logger import warn_once
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, get_model, model_roles
from inspect_ai.model._openai_responses import (
    messages_from_responses_input,
    openai_responses_extra_body_fields,
    responses_model_usage,
    responses_output_items_from_assistant_message,
    responses_tool_choice_param_to_tool_choice,
    responses_tool_params_to_tools,
    tool_choice_from_responses_tool_choice,
    tool_from_responses_tool,
)

logger = getLogger(__file__)


async def inspect_responses_api_request(json_data: dict[str, Any]) -> Response:
    # resolve model
    model = resolve_inspect_model(str(json_data["model"]))
    model_name = model.api.model_name

    # convert openai tools to inspect tools
    responses_tools: list[ToolParam] = json_data.get("tools", [])
    tools = [tool_from_responses_tool(tool) for tool in responses_tools]
    responses_tool_choice: ResponsesToolChoice | None = json_data.get(
        "tool_choice", None
    )
    tool_choice = tool_choice_from_responses_tool_choice(responses_tool_choice)

    # convert to inspect messages
    input: list[ResponseInputItemParam] = json_data["input"]
    messages = messages_from_responses_input(input, tools, model_name)

    # run inference
    output = await model.generate(
        input=messages,
        tool_choice=tool_choice,
        tools=tools,
        config=generate_config_from_openai_responses(json_data),
    )

    # return response
    return Response(
        id=output.message.id or uuid(),
        created_at=int(time()),
        model=model_name,
        object="response",
        output=responses_output_items_from_assistant_message(output.message),
        parallel_tool_calls=False,
        tool_choice=responses_tool_choice_param_to_tool_choice(responses_tool_choice),
        tools=responses_tool_params_to_tools(responses_tools),
        usage=responses_model_usage(output.usage),
    )


def resolve_inspect_model(model_name: str) -> Model:
    if model_name == "inspect":
        model = get_model()
    else:
        model_name = model_name.removeprefix("inspect/")
        if model_name in model_roles():
            model = get_model(role=model_name)
        else:
            model = get_model(model_name)
    return model


def generate_config_from_openai_responses(json_data: dict[str, Any]) -> GenerateConfig:
    # warn for unsupported params
    def warn_unsupported(param: str) -> None:
        if param in json_data:
            warn_once(logger, f"'{param}' option not supported for agent bridge")

    warn_unsupported("background")
    warn_unsupported("prompt")
    warn_unsupported("text")
    warn_unsupported("top_logprobs")

    config = GenerateConfig()
    config.system_message = json_data.get("instructions", None)
    config.max_tokens = json_data.get("max_output_tokens", None)
    config.parallel_tool_calls = json_data.get("parallel_tool_calls", None)
    reasoning = json_data.get("reasoning", None)
    if reasoning:
        if "effort" in reasoning:
            config.reasoning_effort = reasoning["effort"]
        if "summary" in reasoning:
            config.reasoning_summary = reasoning["summary"]
    config.temperature = json_data.get("temperature", None)
    config.top_p = json_data.get("top_p", None)

    # extra_body params (i.e. passthrough for native responses)
    extra_body: dict[str, Any] = {}
    for field in openai_responses_extra_body_fields():
        if field in json_data:
            extra_body[field] = json_data[field]
    if len(extra_body) > 0:
        config.extra_body = extra_body

    # return config
    return config
