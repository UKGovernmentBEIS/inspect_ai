from typing import cast

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig, active_generate_config
from inspect_ai.model._model import Model, active_model, get_model, model_roles
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    _normalize_config,
)


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
