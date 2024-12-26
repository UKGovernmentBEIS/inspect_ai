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

from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment

REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
SERVICES_DIR = "/tmp/inspect-sandbox-services"

ID = "id"
METHOD = "method"
PARAMS = "params"

ERROR = "error"
RESULT = "result"

POLLING_INTERVAL = 0.1

SandboxServiceMethod = Callable[..., Awaitable[JsonValue]]


async def sandbox_service(
    name: str,
    methods: list[SandboxServiceMethod] | dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment,
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
    if isinstance(methods, list):
        methods = {v.__name__: v for v in methods}
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
    for calling back into the main Inspect process.

    To use the service from within a sandbox, either add it to the sys path
    or use importlib. For example, if the service is named 'foo':

    ```python
    import sys
    sys.path.append("/tmp/inspect-sandbox-services/foo")
    import foo
    ```

    Or:

    ```python
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "foo", "/tmp/inspect-sandbox-services/foo/foo.py"
    )
    foo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foo)
    ```
    """

    def __init__(self, name: str, sandbox: SandboxEnvironment) -> None:
        """Create a SandboxService.

        Args:
            name (str): Service name
            sandbox (SandboxEnvironment): Sandbox to publish service to.
        """
        self._name = name
        self._sandbox = sandbox
        self._service_dir = PurePosixPath(SERVICES_DIR, self._name)
        self._methods: dict[str, SandboxServiceMethod] = {}
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
        client_script = PurePosixPath(self._service_dir, f"{self._name}.py").as_posix()
        client_code = self._generate_client()
        await self._write_text_file(client_script, client_code)
        self._client_script = client_script

    async def handle_requests(self) -> None:
        """Handle all pending service requests."""
        # list pending requests
        list_requests = f"ls -1 {self._requests_dir}/*.json"
        result = await self._exec(["bash", "-c", list_requests])

        # process requests
        if result.success:
            request_files = result.stdout.strip().splitlines()
            if request_files:
                await asyncio.gather(
                    *[self._handle_request(file) for file in request_files]
                )

    async def _handle_request(self, request_file: str) -> None:
        # read request
        read_request = f"cat {request_file}"
        result = await self._exec(["bash", "-c", read_request])
        if not result.success:
            raise RuntimeError(
                f"Error reading request for service {self._name}: '{read_request}' ({result.stderr})"
            )

        # parse request
        request_data = json.loads(result.stdout)
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
            exec_rm = await self._exec(["rm", "-f", request_file])
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
        result = await self._exec(["rm", "-rf", rpc_dir])
        result = await self._exec(["mkdir", "-p", rpc_dir])
        if not result.success:
            raise RuntimeError(
                f"Error creating rpc directory '{name}' for sandbox '{self._name}': {result.stderr}"
            )
        return rpc_dir

    async def _write_text_file(self, file: str, contents: str) -> None:
        result = await self._exec(["tee", "--", file], input=contents)
        if not result.success:
            msg = f"Failed to write file '{file}' into container: {result.stderr}"
            raise RuntimeError(msg)

    async def _exec(self, cmd: list[str], input: str | None = None) -> ExecResult[str]:
        try:
            return await self._sandbox.exec(cmd, input=input, timeout=30)
        except TimeoutError:
            raise RuntimeError(
                f"Timed out executing command {' '.join(cmd)} in sandbox"
            )

    def _generate_client(self) -> str:
        return dedent(f"""
        from typing import Any

        def call_{self._name}(method: str, **params: Any) -> Any:
            from time import sleep
            request_id = _write_{self._name}_request(method, **params)
            while True:
                sleep({POLLING_INTERVAL})
                success, result = _read_{self._name}_response(request_id)
                if success:
                    return result

        async def call_{self._name}_async(method: str, **params: Any) -> Any:
            from asyncio import sleep
            request_id = _write_{self._name}_request(method, **params)
            while True:
                await sleep({POLLING_INTERVAL})
                success, result = _read_{self._name}_response(request_id)
                if success:
                    return result

        def _write_{self._name}_request(method: str, **params: Any) -> str:
            from json import dump
            from pathlib import Path
            from uuid import uuid4

            requests_dir = Path("{SERVICES_DIR}", "{self._name}", "{REQUESTS_DIR}")
            request_id = str(uuid4())
            request_data = dict({ID}=request_id, {METHOD}=method, {PARAMS}=params)
            request_path = requests_dir / (request_id + ".json")
            with open(request_path, "w") as f:
                dump(request_data, f)
            return request_id

        def _read_{self._name}_response(request_id: str) -> tuple[bool, Any]:
            from json import load
            from pathlib import Path

            responses_dir = Path("{SERVICES_DIR}", "{self._name}", "{RESPONSES_DIR}")
            response_path = responses_dir / (request_id + ".json")
            if response_path.exists():
                # read and remove the file
                with open(response_path, "r") as f:
                    response = load(f)
                response_path.unlink()

                # raise error if we have one
                if response.get("{ERROR}", None) is not None:
                    raise Exception(response["{ERROR}"])

                # return response if we have one
                elif "{RESULT}" in response:
                    return True, response["{RESULT}"]

                # invalid response
                else:
                    raise RuntimeError(
                        "No {ERROR} or {RESULT} field in response for method " + method
                    )
            else:
                return False, None
        """)
