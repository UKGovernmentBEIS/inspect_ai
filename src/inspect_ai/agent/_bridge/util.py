from typing import cast

from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model import Model, get_model, model_roles
from inspect_ai.tool._tools._web_search._web_search import (
    WebSearchProviders,
    _normalize_config,
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


# input_messages are brand new message instances resulting from conversion so don't
# have the same ids as the last generation -- we want as much id stability as possible
# (for e.g. messages_df) so if the messages are the same as the previous generation
# (modulo id) then copy their id to the input message
def sync_previous_message_ids(
    previous_messages: list[ChatMessage], input_messages: list[ChatMessage]
) -> None:
    for i, previous_message in enumerate(previous_messages):
        # if we are already past the number of input messages then bail
        if i >= len(input_messages):
            break

        # transfer the id from the previous state to the input message if its
        # the same modulo the id
        prev_message_no_id = previous_message.model_copy(update={"id": None})
        input_message_no_id = input_messages[i].model_copy(update={"id": None})
        if prev_message_no_id == input_message_no_id:
            input_messages[i].id = previous_message.id
