from __future__ import annotations

from typing import Any

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders


async def inspect_google_api_request(
    json_data: dict[str, Any],
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: AgentBridge,
) -> dict[str, Any]:
    from .google_api_impl import inspect_google_api_request_impl

    return await inspect_google_api_request_impl(
        json_data, web_search, code_execution, bridge
    )
