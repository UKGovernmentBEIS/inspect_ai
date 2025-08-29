from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._providers.providers import validate_anthropic_client
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders

if TYPE_CHECKING:
    from anthropic.types import Message


async def inspect_anthropic_api_request(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> "Message":
    validate_anthropic_client("agent bridge")

    from .anthropic_api_impl import inspect_anthropic_api_request_impl

    return await inspect_anthropic_api_request_impl(json_data, web_search, bridge)
