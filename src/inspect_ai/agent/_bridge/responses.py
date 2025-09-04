from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

if TYPE_CHECKING:
    from openai.types.responses import Response


async def inspect_responses_api_request(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> "Response":
    validate_openai_client("agent bridge")

    from .responses_impl import inspect_responses_api_request_impl

    return await inspect_responses_api_request_impl(json_data, web_search, bridge)
