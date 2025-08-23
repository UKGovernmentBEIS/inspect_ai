from typing import Awaitable, Callable

import anyio
from pydantic import JsonValue

from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.tool._tools._web_search._web_search import WebSearchProviders
from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service

from ..completions import inspect_completions_api_request

MODEL_SERVICE = "bridge_model_service"

from logging import getLogger  # noqa: E402

logger = getLogger(__file__)


async def run_model_service(
    sandbox: SandboxEnvironment, web_search: WebSearchProviders, started: anyio.Event
) -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods=[generate_completions(), generate_responses(web_search)],
        until=lambda: False,
        sandbox=sandbox,
        started=started,
    )


def generate_completions() -> Callable[
    [dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]
]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        completion = await inspect_completions_api_request(json_data)
        return completion.model_dump(mode="json")

    return generate


def generate_responses(
    web_search: WebSearchProviders,
) -> Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]]:
    async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        completion = await inspect_responses_api_request(json_data, web_search)
        return completion.model_dump(mode="json")

    return generate
