from typing import Sequence, cast

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig, active_generate_config
from inspect_ai.model._model import (
    GenerateInput,
    Model,
    active_model,
    get_model,
    model_roles,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo, parse_tool_info
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    _normalize_config,
)


async def bridge_generate(
    bridge: AgentBridge,
    model: Model,
    input: list[ChatMessage],
    tools: Sequence[ToolInfo | Tool],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> ModelOutput:
    output: ModelOutput | None = None
    if bridge.filter:
        tool_info = [
            parse_tool_info(tool) if not isinstance(tool, ToolInfo) else tool
            for tool in tools
        ]
        result = await bridge.filter(model.name, input, tool_info, tool_choice, config)
        if isinstance(result, ModelOutput):
            output = result
        elif isinstance(result, GenerateInput):
            input, tools, tool_choice, config = result

    # if the filter didn't take it then run normal inference
    if output is None:
        refusals = 0
        while True:
            output = await model.generate(
                input=input,
                tool_choice=tool_choice,
                tools=tools,
                config=config,
            )
            if (
                output.stop_reason == "content_filter"
                and bridge.retry_refusals is not None
                and refusals < bridge.retry_refusals
            ):
                refusals += 1
            else:
                break

    # return output
    return output


def resolve_generate_config(
    model: Model, bridge_config: GenerateConfig
) -> GenerateConfig:
    # give config built into the model instance priority over
    # bridged agent default
    config = bridge_config.merge(model.config)

    # apply active model config if appropriate
    is_active_model = model == active_model()
    if is_active_model:
        config = config.merge(active_generate_config())

    return config


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


def resolve_web_search_providers(
    providers: WebSearchProviders | None,
) -> WebSearchProviders:
    if providers is None:
        providers = internal_web_search_providers()
    return cast(WebSearchProviders, _normalize_config(providers))


def internal_web_search_providers() -> WebSearchProviders:
    return WebSearchProviders(
        openai=True, anthropic=True, grok=True, gemini=True, perplexity=True
    )


def apply_message_ids(bridge: AgentBridge, messages: list[ChatMessage]) -> None:
    # clear the ids so we can apply new ones
    for message in messages:
        message.id = None

    # allocate ids based on message content (re-applying the same id for the same
    # content, but also ensuring that if an id is already used we generate a new one)
    for message in messages:
        message.id = bridge._id_for_message(message, messages)
