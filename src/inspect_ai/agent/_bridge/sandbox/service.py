import json
from logging import getLogger  # noqa: E402
from typing import Any, Awaitable, Callable

import anyio
from pydantic import JsonValue

from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service

from ..anthropic_api import inspect_anthropic_api_request
from ..completions import inspect_completions_api_request
from ..google_api import inspect_google_api_request
from ..responses import inspect_responses_api_request
from .types import SandboxAgentBridge

logger = getLogger(__name__)

MODEL_SERVICE = "bridge_model_service"


async def run_model_service(
    sandbox: SandboxEnvironment,
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: SandboxAgentBridge,
    instance: str,
    started: anyio.Event,
) -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods={
            "generate_completions": generate_completions(bridge),
            "generate_responses": generate_responses(
                web_search, code_execution, bridge
            ),
            "generate_anthropic": generate_anthropic(
                web_search, code_execution, bridge
            ),
            "generate_google": generate_google(web_search, code_execution, bridge),
            "list_tools": list_tools(bridge),
            "call_tool": call_tool(bridge),
        },
        until=lambda: False,
        sandbox=sandbox,
        instance=instance,
        polling_interval=2,
        started=started,
        requires_python=False,
    )


def generate_completions(
    bridge: SandboxAgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _resolve_model(bridge.model, json_data)
        completion = await inspect_completions_api_request(json_data, None, bridge)
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_responses(
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: SandboxAgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _resolve_model(bridge.model, json_data)
        completion = await inspect_responses_api_request(
            json_data, None, web_search, code_execution, bridge
        )
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_anthropic(
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: SandboxAgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _resolve_model(bridge.model, json_data)
        completion = await inspect_anthropic_api_request(
            json_data, None, web_search, code_execution, bridge
        )
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_google(
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: SandboxAgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _resolve_model(bridge.model, json_data)
        completion = await inspect_google_api_request(
            json_data, web_search, code_execution, bridge
        )
        return completion

    return generate


# resolve model to a pre-specified value if model passed in the request
# is not specifially an inspect model (enables a fallthrough for scaffolds
# that can't be invoked in such as way as to full control their model)
def _resolve_model(model: str | None, json_data: dict[str, JsonValue]) -> None:
    if model is not None:
        request_model = str(json_data.get("model", ""))
        if request_model != "inspect" or not model.startswith("inspect/"):
            json_data["model"] = model


def list_tools(
    bridge: SandboxAgentBridge,
) -> Callable[[str], Awaitable[JsonValue]]:
    """Return tool schemas for a bridged tools server."""

    async def execute(server: str) -> JsonValue:
        if server not in bridge.bridged_tools:
            raise ValueError(f"Unknown bridged tools server: {server}")

        tools = list(bridge.bridged_tools[server].values())
        tools_info = get_tools_info(tools)

        return [
            {
                "name": info.name,
                "description": info.description,
                "inputSchema": info.parameters.model_dump(exclude_none=True),
            }
            for info in tools_info
        ]

    return execute


def call_tool(
    bridge: SandboxAgentBridge,
) -> Callable[[str, str, dict[str, Any]], Awaitable[str]]:
    """Execute a bridged tool and return result."""

    async def execute(server: str, tool: str, arguments: dict[str, Any]) -> str:
        if server not in bridge.bridged_tools:
            raise ValueError(f"Unknown bridged tools server: {server}")

        server_tools = bridge.bridged_tools[server]
        if tool not in server_tools:
            raise ValueError(f"Unknown tool '{tool}' in server '{server}'")

        tool_fn = server_tools[tool]
        result = await tool_fn(**arguments)

        # MCP returns strings, so serialize if needed
        if isinstance(result, str):
            return result
        return json.dumps(result)

    return execute
