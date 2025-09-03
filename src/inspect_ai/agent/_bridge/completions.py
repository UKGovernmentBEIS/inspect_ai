from __future__ import annotations

from logging import getLogger
from time import time
from typing import TYPE_CHECKING, Any

from shortuuid import uuid

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._generate_config import (
    GenerateConfig,
    ResponseSchema,
)
from inspect_ai.model._openai_convert import messages_from_openai
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema

from .util import apply_message_ids, resolve_generate_config, resolve_inspect_model

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionToolChoiceOptionParam,
        ChatCompletionToolParam,
    )


logger = getLogger(__file__)


async def inspect_completions_api_request(
    json_data: dict[str, Any],
    bridge: AgentBridge,
) -> "ChatCompletion":
    validate_openai_client("agent bridge")

    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionMessageParam,
    )

    from inspect_ai.model._openai import (
        openai_chat_choices,
        openai_completion_usage,
    )

    bridge_model_name = str(json_data["model"])
    model = resolve_inspect_model(bridge_model_name)
    model_name = model.api.model_name

    # convert openai messages to inspect messages
    messages: list[ChatCompletionMessageParam] = json_data["messages"]
    input = await messages_from_openai(messages, model_name)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_openai_completions(json_data)
    if config.system_message is not None:
        input.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, input)

    # read openai tools and tool choice
    openai_tools: list[ChatCompletionToolParam] = json_data.get("tools", [])
    tools = tools_from_openai_tools(openai_tools)
    openai_tool_choice: ChatCompletionToolChoiceOptionParam | None = json_data.get(
        "tool_choice", None
    )
    tool_choice = tool_choice_from_openai_tool_choice(openai_tool_choice)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    output = await model.generate(
        input=input,
        tools=tools,
        tool_choice=tool_choice,
        config=config,
    )

    # update state
    if bridge_model_name == "inspect":
        bridge.state.messages = input + [output.message]
        bridge.state.output = output

    # inspect completion to openai completion
    return ChatCompletion(
        id=uuid(),
        created=int(time()),
        object="chat.completion",
        choices=openai_chat_choices(output.choices),
        model=model_name,
        usage=openai_completion_usage(output.usage) if output.usage else None,
    )


def tool_choice_from_openai_tool_choice(
    tool_choice: "ChatCompletionToolChoiceOptionParam" | None,
) -> ToolChoice | None:
    inspect_tool_choice: ToolChoice | None = None
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
    return inspect_tool_choice


def tools_from_openai_tools(tools: "list[ChatCompletionToolParam]") -> list[ToolInfo]:
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
    return inspect_tools


def generate_config_from_openai_completions(
    json_data: dict[str, Any],
) -> GenerateConfig:
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
