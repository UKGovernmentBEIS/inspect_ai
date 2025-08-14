from pydantic import JsonValue

from inspect_ai.util._sandbox import sandbox, sandbox_service

from ..request import inspect_model_request

MODEL_SERVICE = "bridge_model_service"


async def run_model_service() -> None:
    await sandbox_service(
        name=MODEL_SERVICE,
        methods=[generate],
        until=lambda: True,
        sandbox=sandbox(),
    )


async def generate(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    completion = await inspect_model_request(json_data)
    return completion.model_dump(mode="json")
