import asyncio
import json
import time
from pathlib import Path, PurePosixPath
from typing import (
    Awaitable,
    Callable,
    cast,
)

from pydantic import JsonValue
from shortuuid import uuid

from inspect_ai.util import SandboxEnvironment, sandbox

REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
CLIENT_SCRIPT = "client.py"
SERVICES_DIR = "/tmp/inspect-sandbox-services"

ID = "id"
METHOD = "method"
PARAMS = "params"

ERROR = "error"
RESULT = "result"

SandboxServiceMethod = Callable[..., Awaitable[JsonValue]]


async def sandbox_service(
    name: str,
    sandbox: SandboxEnvironment,
    methods: dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    interval: float = 0.2,
) -> None:
    # setup and start service
    service = SandboxService(name, sandbox)
    for name, method in methods.items():
        service.add_method(name, method)
    await service.start()

    # wait for and process methods
    while not until():
        await asyncio.sleep(interval)
        await service.handle_requests()


class SandboxService:
    def __init__(self, name: str, sandbox: SandboxEnvironment = sandbox()) -> None:
        self._name = name
        self._sandbox = sandbox
        self._service_dir = PurePosixPath(SERVICES_DIR, self._name)
        self._methods: dict[str, SandboxServiceMethod]
        self._requests_dir: str = ""
        self._responses_dir: str = ""
        self._client_script: str = ""

    def add_method(self, name: str, method: SandboxServiceMethod) -> None:
        self._methods[name] = method

    async def start(self) -> None:
        # requests dir
        assert not self._requests_dir
        self._requests_dir = await self._create_rpc_dir(REQUESTS_DIR)

        # responses dir
        assert not self._responses_dir
        self._responses_dir = await self._create_rpc_dir(RESPONSES_DIR)

        # client script
        assert not self._client_script
        client_script = PurePosixPath(self._service_dir, CLIENT_SCRIPT).as_posix()
        client_code = self._generate_client_code()
        await self._write_text_file(client_script, client_code)
        self._client_script = client_script

    async def handle_requests(self) -> None:
        # read pending request files
        result = await self._sandbox.exec(["ls", "-1", f"{self._requests_dir}/*.json"])
        if not result.success:
            raise RuntimeError(
                f"Error reading service requests for '{self._name}' service."
            )
        request_files = result.stdout.strip().splitlines()

        # handle requests in parallel
        await asyncio.gather(*[self._handle_request(file) for file in request_files])

    async def _handle_request(self, request_file: str) -> None:
        # read and validate request
        with open(request_file, "r") as f:
            request_data = json.load(f)
        if not isinstance(request_data, dict):
            raise TypeError(f"Service request is not a dict (type={request_data})")

        # read id (after we have this we can write responses)
        request_id = request_data.get(ID, None)
        if not isinstance(request_id, str):
            raise TypeError(
                f"Service request id is not a string (type={type(request_id)})"
            )

        # helpers to write responses and errors

        async def write_response(
            result: JsonValue | None, error: str | None = None
        ) -> None:
            # form response payload
            response_data = {
                ID: request_id,
                RESULT: result,
                ERROR: error,
            }

            # compute response path
            response_path = PurePosixPath(
                self._responses_dir, f"{request_id}.json"
            ).as_posix()

            # write response
            await self._write_text_file(response_path, json.dumps(response_data))

            # remove request file
            exec_rm = await self._sandbox.exec(["rm", "-f", request_file])
            if not exec_rm.success:
                raise RuntimeError(
                    f"Error removing request file '{request_file}': {exec_rm.stderr}"
                )

        async def write_error_response(error: str) -> None:
            await write_response(None, error)

        # read and validate params
        method_name = request_data.get(METHOD, None)
        params = request_data.get(PARAMS, None)
        if not isinstance(method_name, str):
            await write_error_response(
                f"Service {METHOD} not passed or not a string (type={type(method_name)})"
            )
        elif method_name not in self._methods:
            await write_error_response(f"Unknown method '{method_name}'")
        elif not isinstance(params, dict):
            await write_error_response(
                f"{PARAMS} not passed or not a dict (type={params})"
            )

        # all clear, call the method
        else:
            try:
                params = cast(dict[str, JsonValue], request_data.get(PARAMS))
                method = self._methods[method_name]
                await write_response(await method(**params))
            except Exception as err:
                await write_error_response(f"Error calling method {method_name}: {err}")

    async def _create_rpc_dir(self, name: str) -> str:
        rpc_dir = PurePosixPath(self._service_dir, name).as_posix()
        result = await self._sandbox.exec(["mkdir", "-p", rpc_dir])
        if not result.success:
            raise RuntimeError(
                f"Error creating rpc directory '{name}' for sandbox '{self._name}': {result.stderr}"
            )
        return rpc_dir

    async def _write_text_file(self, file: str, contents: str) -> None:
        result = await self._sandbox.exec(["tee", "--", file], input=contents)
        if not result.success:
            msg = f"Failed to write file '{file}' into container: {result.stderr}"
            raise RuntimeError(msg)

    def _generate_client_code(self) -> str:
        return ""


def call_inspect_service(
    service: str, method: str, params: dict[str, JsonValue]
) -> JsonValue:
    # directories
    requests_dir = Path(SERVICES_DIR, service, REQUESTS_DIR)
    responses_dir = Path(SERVICES_DIR, service, RESPONSES_DIR)

    # create request and write it
    request_id = uuid()
    request_data = {ID: request_id, METHOD: method, PARAMS: params}
    request_path = requests_dir / f"{request_id}.json"
    with open(request_path, "w") as f:
        json.dump(request_data, f)

    # wait for response
    response_path = responses_dir / f"{request_id}.json"
    while True:
        time.sleep(0.2)
        if response_path.exists():
            # read and remove the file
            with open(response_path, "r") as f:
                response = json.load(f)
            response_path.unlink()

            # raise error if necessary
            if response[ERROR]:
                raise Exception(response[ERROR])

            # return response
            return response[RESULT]
