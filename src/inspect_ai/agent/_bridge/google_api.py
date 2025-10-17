from __future__ import annotations

from typing import Any

from google.genai.types import GenerateContentResponse

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._providers.providers import validate_google_client
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders


async def inspect_google_api_request(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> GenerateContentResponse:
    validate_google_client("agent bridge")

    from .google_api_impl import inspect_google_api_request_impl

    return await inspect_google_api_request_impl(json_data, web_search, bridge)


def google_api_model_name(json_data: dict[str, Any]) -> str | None:
    from .google_api_impl import google_api_model_name_impl

    return google_api_model_name_impl(json_data)
