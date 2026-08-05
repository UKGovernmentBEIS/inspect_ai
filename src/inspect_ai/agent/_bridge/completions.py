from __future__ import annotations

from logging import getLogger
from time import time
from typing import TYPE_CHECKING, Any

from shortuuid import uuid

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import ModelName
from inspect_ai.model._openai_convert import messages_from_openai
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams

from ._errors import BridgePolicyError
from .util import (
    apply_message_ids,
    bridge_generate,
    clear_generation_params,
    client_json_schema,
    client_request_object,
    client_request_string,
    client_response_schema,
    resolve_generate_config,
    resolve_inspect_model,
    tool_choice_from_openai_string,
    validate_bridge_media,
    validate_client_config,
)

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionToolParam,
    )


logger = getLogger(__name__)


async def inspect_completions_api_request(
    json_data: dict[str, Any],
    headers: dict[str, str] | None,
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
    model = resolve_inspect_model(bridge_model_name, bridge.model_aliases, bridge.model)
    model_name = model.api.model_name

    # convert openai messages to inspect messages
    openai_messages: list[ChatCompletionMessageParam] = json_data["messages"]
    messages = await messages_from_openai(openai_messages, model_name)
    await validate_bridge_media(bridge, messages)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_openai_completions(json_data)
    if not bridge.forward_generation_config:
        clear_generation_params(config)
    validate_client_config(config)
    config.extra_headers = headers
    if config.system_message is not None:
        messages.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # read openai tools and tool choice
    openai_tools: list[ChatCompletionToolParam] = json_data.get("tools", [])
    tools = tools_from_openai_tools(openai_tools)
    tool_choice = tool_choice_from_openai_tool_choice(
        json_data.get("tool_choice", None)
    )

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # if there is a bridge filter give it a shot first
    output, c_message = await bridge_generate(
        bridge, model, messages, tools, tool_choice, config
    )
    if c_message is not None:
        messages.append(c_message)

    # update state if we have more messages than the last generation
    await bridge._track_state(messages, output, str(ModelName(model)))

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
    tool_choice: Any,
) -> ToolChoice | None:
    # `Any` rather than `ChatCompletionToolChoiceOptionParam`: the value is
    # client-controlled JSON, so its shape is guarded before the first subscript
    # for a mistyped value to 400 rather than escape as a raw `TypeError`/`KeyError`.
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return tool_choice_from_openai_string(tool_choice, "tool_choice")
    tool_choice = client_request_object(tool_choice, "tool_choice")
    tool_type = tool_choice.get("type", None)
    if tool_type != "function":
        # `custom` and `allowed_tools` are valid API values the bridge does not
        # translate; previously a bare `assert` (status-less `AssertionError`).
        raise BridgePolicyError(
            "invalid request field in bridged request (tool_choice.type: only "
            f"'function' is supported by the agent bridge, got {tool_type!r})"
        )
    function = (
        client_request_object(tool_choice.get("function", None), "tool_choice.function")
        or {}
    )
    return ToolFunction(
        name=client_request_string(
            function.get("name", None), "tool_choice.function.name"
        )
    )


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
    response_format = client_request_object(
        json_data.get("response_format", None), "response_format"
    )
    if response_format is not None:
        json_schema = client_request_object(
            response_format.get("json_schema", None), "response_format.json_schema"
        )
        if json_schema is not None:
            config.response_schema = client_response_schema(
                name=json_schema.get("name", "schema"),
                description=json_schema.get("description", None),
                json_schema=client_json_schema(
                    json_schema.get("schema", {}),
                    "response_format.json_schema.schema",
                ),
                strict=json_schema.get("strict", None),
                dialect_field="response_format.json_schema",
            )

    return config
