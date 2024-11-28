import asyncio
import json
from pathlib import PurePosixPath
from textwrap import dedent
from typing import (
    Awaitable,
    Callable,
    cast,
)

from pydantic import JsonValue

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

POLLING_INTERVAL = 0.1

SandboxServiceMethod = Callable[..., Awaitable[JsonValue]]
"""Method definition for sandbox service.

Service methods should accept and return arguments of type JsonValue
"""


async def sandbox_service(
    name: str,
    methods: dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment = sandbox(),
) -> None:
    """Run a service that is callable from within a sandbox.

    Args:
        name (str): Service name
        methods (dict[str, SandboxServiceMethod]): Service methods.
        until (Callable[[], bool]): Function used to check whether
          the service should stop.
        sandbox (SandboxEnvironment): Sandbox to publish service to.
    """
    # setup and start service
    service = SandboxService(name, sandbox)
    for name, method in methods.items():
        service.add_method(name, method)
    await service.start()

    # wait for and process methods
    while not until():
        await asyncio.sleep(POLLING_INTERVAL)
        await service.handle_requests()


class SandboxService:
    """Sandbox service.

    Service that makes available a set of methods to a sandbox
    for calling back into main Inspect solver / scaffold.
    """

    def __init__(self, name: str, sandbox: SandboxEnvironment = sandbox()) -> None:
        """Create a SandboxService.

        Args:
            name (str): Service name
            sandbox (SandboxEnvironment): Sandbox to publish service to.
        """
        self._name = name
        self._sandbox = sandbox
        self._service_dir = PurePosixPath(SERVICES_DIR, self._name)
        self._methods: dict[str, SandboxServiceMethod]
        self._requests_dir: str = ""
        self._responses_dir: str = ""
        self._client_script: str = ""

    def add_method(self, name: str, method: SandboxServiceMethod) -> None:
        """Add a method to the service.

        Args:
            name (str): Method name.
            method (SandboxServiceMethod): Function that implements method.
        """
        self._methods[name] = method

    async def start(self) -> None:
        """Start running the service."""
        # requests dir
        assert not self._requests_dir
        self._requests_dir = await self._create_rpc_dir(REQUESTS_DIR)

        # responses dir
        assert not self._responses_dir
        self._responses_dir = await self._create_rpc_dir(RESPONSES_DIR)

        # client script
        assert not self._client_script
        client_script = PurePosixPath(self._service_dir, CLIENT_SCRIPT).as_posix()
        client_code = self._generate_client()
        await self._write_text_file(client_script, client_code)
        self._client_script = client_script

    async def handle_requests(self) -> None:
        """Handle all pending service requests."""
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

    def _generate_client(self) -> str:
        return dedent(f"""
        async def call_{self._name}(method: str, params: dict[str, JsonValue]
        ) -> JsonValue:
            # dependencies
            from json import dump, load
            from uuid import uuid4
            from pathlib import Path

            # directories
            requests_dir = Path("{SERVICES_DIR}", "{self._name}", "{REQUESTS_DIR}")
            responses_dir = Path("{SERVICES_DIR}", "{self._name}", "{RESPONSES_DIR}")

            # create request and write it
            request_id = uuid4()
            request_data = dict({ID}=request_id, {METHOD}=method, {PARAMS}=params)
            request_path = requests_dir / request_id + ".json"
            with open(request_path, "w") as f:
                dump(request_data, f)

            # wait for response
            response_path = responses_dir / request_id + ".json"
            while True:
                # initial wait
                await asyncio.sleep({POLLING_INTERVAL})

                if response_path.exists():
                    # read and remove the file
                    with open(response_path, "r") as f:
                        response = load(f)
                    response_path.unlink()

                    # raise error if we have one
                    if "{ERROR}" in response:
                        raise Exception(response["{ERROR}"])

                    # return response if we have one
                    elif "{RESULT}" in response:
                        return response["{RESULT}"]

                    # invalid response
                    else:
                        raise RuntimeError(
                            "No {ERROR} or {RESULT} field in response for method " + method
                        )
        """)
