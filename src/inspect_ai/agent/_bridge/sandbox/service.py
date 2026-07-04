from logging import getLogger  # noqa: E402
from typing import Any, Awaitable, Callable, cast

import anyio
from pydantic import JsonValue

from inspect_ai._util.json import to_json_str_safe
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.tool._tools._code_execution import CodeExecutionProviders
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service

from .._errors import PROVIDER_ERROR_KEY, provider_error_payload
from ..anthropic_api import inspect_anthropic_api_request
from ..completions import inspect_completions_api_request
from ..google_api import inspect_google_api_request
from ..responses import inspect_responses_api_request
from .types import SandboxAgentBridge

logger = getLogger(__name__)

MODEL_SERVICE = "bridge_model_service"

GenerateMethod = Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]


def _forward_provider_errors(generate: GenerateMethod) -> GenerateMethod:
    """Convert a failed generate into a forwardable provider-error result.

    Any exception from the wrapped generate is returned (not raised) under
    `PROVIDER_ERROR_KEY` so the sandbox service RPC delivers it via the `result`
    channel. This lets the model proxy emit a provider-dialect error response
    and stay up, instead of the RPC `error` channel triggering a fatal exit.
    """

    async def generate_forwarding_errors(
        json_data: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        try:
            return await generate(json_data)
        except Exception as ex:
            return {PROVIDER_ERROR_KEY: cast(JsonValue, provider_error_payload(ex))}

    return generate_forwarding_errors


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
            "generate_completions": _forward_provider_errors(
                generate_completions(bridge)
            ),
            "generate_responses": _forward_provider_errors(
                generate_responses(web_search, code_execution, bridge)
            ),
            "generate_anthropic": _forward_provider_errors(
                generate_anthropic(web_search, code_execution, bridge)
            ),
            "generate_google": _forward_provider_errors(
                generate_google(web_search, code_execution, bridge)
            ),
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
        completion = await inspect_completions_api_request(json_data, None, bridge)
        return completion.model_dump(mode="json", warnings=False)

    return generate


def generate_responses(
    web_search: WebSearchProviders,
    code_execution: CodeExecutionProviders,
    bridge: SandboxAgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
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
        completion = await inspect_google_api_request(
            json_data, web_search, code_execution, bridge
        )
        return completion

    return generate


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

        # Plain strings are returned verbatim (the MCP `tools/call` text part
        # carries them as-is). For anything else, use pydantic_core.to_json so
        # Pydantic models (e.g. list[ContentText] from real MCP tools) are
        # serialized correctly — json.dumps can't handle BaseModel.
        if isinstance(result, str):
            return result
        return to_json_str_safe(result)

    return execute
