from typing import Awaitable, Callable

import anyio
from pydantic import JsonValue

from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service

from ..anthropic_api import inspect_anthropic_api_request
from ..completions import inspect_completions_api_request
from ..responses import inspect_responses_api_request
from ..types import AgentBridge

MODEL_SERVICE = "bridge_model_service"

from logging import getLogger  # noqa: E402

logger = getLogger(__file__)


async def run_model_service(
    sandbox: SandboxEnvironment,
    web_search: WebSearchProviders,
    bridge: AgentBridge,
    instance: str,
    started: anyio.Event,
) -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods={
            "generate_completions": generate_completions(bridge),
            "generate_responses": generate_responses(web_search, bridge),
            "generate_anthropic": generate_anthropic(web_search, bridge),
        },
        until=lambda: False,
        sandbox=sandbox,
        instance=instance,
        started=started,
    )


def generate_completions(
    bridge: AgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        completion = await inspect_completions_api_request(json_data, bridge)
        return completion.model_dump(mode="json")

    return generate


def generate_responses(
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        completion = await inspect_responses_api_request(json_data, web_search, bridge)
        return completion.model_dump(mode="json")

    return generate


def generate_anthropic(
    web_search: WebSearchProviders,
    bridge: AgentBridge,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        completion = await inspect_anthropic_api_request(json_data, web_search, bridge)
        return completion.model_dump(mode="json")

    return generate
