from typing import cast

from inspect_ai.agent._agent import AgentState
from inspect_ai.model._chat_message import ChatMessage, ChatMessageAssistant
from inspect_ai.model._model import Model, get_model, model_roles
from inspect_ai.model._model_output import ModelOutput
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


def update_state_from_generate(
    input: list[ChatMessage], output: ModelOutput, state: AgentState
) -> None:
    # if the state ends with an assistant message its a continuation
    # of a thread (rather than the initialization of the agent)
    # so find and append messages in the input that are after the
    # the last assistant message
    if is_awaiting_response(state.messages):
        state.messages.extend(previous_turn_response(input))

    # append assistant message and update output
    state.messages.append(output.message)
    state.output = output


def is_awaiting_response(messages: list[ChatMessage]) -> bool:
    return len(messages) > 0 and isinstance(messages[-1], ChatMessageAssistant)


def previous_turn_response(messages: list[ChatMessage]) -> list[ChatMessage]:
    # if there are no assistant messages this model might not replay
    # assistant messages -- in that case just return the last message)
    if not any(isinstance(message, ChatMessageAssistant) for message in messages):
        return [messages[-1]]
    else:
        # walk backwards until we find the most recent assistant message
        idx = len(messages) - 1
        while idx >= 0 and not isinstance(messages[idx], ChatMessageAssistant):
            idx -= 1

        # return everything after that index
        return messages[idx + 1 :]
