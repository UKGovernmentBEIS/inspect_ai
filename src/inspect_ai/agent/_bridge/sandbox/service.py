import anyio
from pydantic import JsonValue

from inspect_ai.util._sandbox import SandboxEnvironment, sandbox_service

from ..request import inspect_model_request

MODEL_SERVICE = "bridge_model_service"

from logging import getLogger  # noqa: E402

logger = getLogger(__file__)


async def run_model_service(sandbox: SandboxEnvironment, started: anyio.Event) -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods=[generate],
        until=lambda: False,
        sandbox=sandbox,
        started=started,
    )


async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    completion = await inspect_model_request(json_data)
    return completion.model_dump(mode="json")
