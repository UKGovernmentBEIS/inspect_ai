import json
from logging import getLogger
from pathlib import PurePosixPath
from textwrap import dedent
from typing import (
    Awaitable,
    Callable,
    cast,
)

import anyio
from pydantic import JsonValue

from inspect_ai._util._async import coro_log_exceptions
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment

logger = getLogger(__name__)


REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
SERVICES_DIR = "/var/tmp/sandbox-services"

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
    user: str | None = None,
    instance: str | None = None,
    polling_interval: float | None = None,
    started: anyio.Event | None = None,
) -> None:
    """Run a service that is callable from within a sandbox.

    The service makes available a set of methods to a sandbox
    for calling back into the main Inspect process.

    To use the service from within a sandbox, either add it to the sys path
    or use importlib. For example, if the service is named 'foo':

    ```python
    import sys
    sys.path.append("/var/tmp/sandbox-services/foo")
    import foo
    ```

    Or:

    ```python
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "foo", "/var/tmp/sandbox-services/foo/foo.py"
    )
    foo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foo)
    ```

    Args:
        name: Service name
        methods: Service methods.
        until: Function used to check whether the service should stop.
        sandbox: Sandbox to publish service to.
        user: User to login as. Defaults to the sandbox environment's default user.
        instance: If you want multiple instances of a service in a single sandbox
            then use the `instance` param.
        polling_interval: Polling interval for request checking. If not specified uses
            sandbox specific default (2 seconds if not specified, 0.2 seconds for Docker).
        started: Event to set when service has been started
    """
    # validate python in sandbox
    await validate_sandbox_python(name, sandbox, user)

    # sort out polling interval
    default_polling_interval = sandbox.default_polling_interval()
    if polling_interval is None:
        polling_interval = default_polling_interval
    else:
        # use the default as a limit which you can't go beneath
        polling_interval = max(polling_interval, default_polling_interval)

    # setup and start service
    service = SandboxService(name, sandbox, user, instance, started)
    if isinstance(methods, list):
        methods = {v.__name__: v for v in methods}
    for name, method in methods.items():
        service.add_method(name, method)
    await service.start()

    # wait for and process methods
    while not until():
        await anyio.sleep(polling_interval)
        await service.handle_requests()


class SandboxService:
    """Sandbox service.

    Service that makes available a set of methods to a sandbox
    for calling back into the main Inspect process.

    To use the service from within a sandbox, either add it to the sys path
    or use importlib. For example, if the service is named 'foo':

    ```python
    import sys
    sys.path.append("/var/tmp/sandbox-services/foo")
    import foo
    ```

    Or:

    ```python
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "foo", "/var/tmp/sandbox-services/foo/foo.py"
    )
    foo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foo)
    ```

    If you are using an `instance`, then include that in the
    path after the service name:

    ```python
    spec = importlib.util.spec_from_file_location(
        "foo", "/var/tmp/sandbox-services/foo/<instance>/foo.py"
    )
    ```
    """

    def __init__(
        self,
        name: str,
        sandbox: SandboxEnvironment,
        user: str | None = None,
        instance: str | None = None,
        started: anyio.Event | None = None,
    ) -> None:
        """Create a SandboxService.

        Args:
            name (str): Service name
            sandbox (SandboxEnvironment): Sandbox to publish service to.
            user (str | None): User to login as. Defaults to the sandbox environment's
              default user.
            instance: Unique identifier for an instance of this named service
               (should be a valid posix filename)
            started: Event to set when service has been started
        """
        self._name = name
        self._sandbox = sandbox
        self._user = user
        self._started = started
        self._service_dir = PurePosixPath(SERVICES_DIR, self._name)
        self._root_service_dir = self._service_dir
        if instance is not None:
            self._service_dir = self._service_dir / instance
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

        # set started event if provided
        if self._started:
            self._started.set()

    async def handle_requests(self) -> None:
        """Handle all pending service requests."""
        # list pending requests
        list_requests = f"ls -1 {self._requests_dir}/*.json"
        result = await self._exec(["bash", "-c", list_requests])

        # process requests
        if result.success:
            request_files = result.stdout.strip().splitlines()
            if request_files:
                async with anyio.create_task_group() as tg:
                    for file in request_files:
                        tg.start_soon(
                            coro_log_exceptions,
                            logger,
                            "handling sandbox service request",
                            self._handle_request,
                            file,
                        )

    async def _handle_request(self, request_file: str) -> None:
        # read request
        read_request = f"cat {request_file}"
        result = await self._exec(["bash", "-c", read_request])
        if not result.success:
            raise RuntimeError(
                f"Error reading request for service {self._name}: '{read_request}' ({result.stderr})"
            )

        # parse request (decode error could occur if its incomplete so bypass this)
        try:
            request_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning(
                f"JSON decoding error reading service request: {result.stdout}"
            )
            return None
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
            from inspect_ai.log._samples import sample_active
            from inspect_ai.util._limit import LimitExceededError

            try:
                params = cast(dict[str, JsonValue], request_data.get(PARAMS))
                try:
                    method = self._methods[method_name]
                    await write_response(await method(**params))
                except LimitExceededError as ex:
                    active = sample_active()
                    if active is not None:
                        active.limit_exceeded(ex)
                    await write_error_response(
                        f"Limit exceeded calling method {method_name}: {ex.message}"
                    )
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
            return await self._sandbox.exec(
                cmd, user=self._user, input=input, timeout=30, concurrency=False
            )
        except TimeoutError:
            raise RuntimeError(
                f"Timed out executing command {' '.join(cmd)} in sandbox"
            )

    # NOTE: A snapshot of the generated code for the bridge_model_service lives
    # within the bridge model proxy implementation. If you change this method you
    # should therefore re-generate this source code and sync it to the proxy:
    #   sandbox_service_script('bridge_model_service')
    # in point of fact we don't expect this code to ever change which is why
    # we haven't invested in an automated code syncing regimen.
    def _generate_client(self) -> str:
        return dedent(f"""
        from typing import Any

        def call_{self._name}(method: str, **params: Any) -> Any:
            from time import sleep
            request_id = _write_{self._name}_request(method, **params)
            while True:
                sleep({POLLING_INTERVAL})
                success, result = _read_{self._name}_response(request_id, method)
                if success:
                    return result

        async def call_{self._name}_async(method: str, **params: Any) -> Any:
            from asyncio import sleep
            request_id = _write_{self._name}_request(method, **params)
            while True:
                await sleep({POLLING_INTERVAL})
                success, result = _read_{self._name}_response(request_id, method)
                if success:
                    return result

        def _write_{self._name}_request(method: str, **params: Any) -> str:
            from json import dump
            from uuid import uuid4

            requests_dir = _{self._name}_service_dir("{REQUESTS_DIR}")
            request_id = str(uuid4())
            request_data = dict({ID}=request_id, {METHOD}=method, {PARAMS}=params)
            request_path = requests_dir / (request_id + ".json")
            with open(request_path, "w") as f:
                dump(request_data, f)
            return request_id

        def _read_{self._name}_response(request_id: str, method: str) -> tuple[bool, Any]:
            from json import JSONDecodeError, load

            responses_dir = _{self._name}_service_dir("{RESPONSES_DIR}")
            response_path = responses_dir / (request_id + ".json")
            if response_path.exists():
                # read and remove the file
                with open(response_path, "r") as f:
                    # it's possible the file is still being written so
                    # just catch and wait for another retry if this occurs
                    try:
                        response = load(f)
                    except JSONDecodeError:
                        return False, None
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

        def _{self._name}_service_dir(subdir: str) -> Any:
            import os
            from pathlib import Path
            service_dir = Path("{self._root_service_dir}")
            instance = os.environ.get("{self._name.upper()}_INSTANCE", None)
            if instance is not None:
                service_dir = service_dir / instance
            return service_dir / subdir
        """)


def sandbox_service_script(name: str) -> str:
    # create a service just to generate the script (pass no sandbox)
    service = SandboxService(name, None)  # type: ignore[arg-type]
    return service._generate_client()


async def validate_sandbox_python(
    service_name: str, sandbox: SandboxEnvironment, user: str | None = None
) -> None:
    # validate python in sandbox
    result = await sandbox.exec(["which", "python3"], user=user, concurrency=False)
    if not result.success:
        raise PrerequisiteError(
            f"The {service_name} requires that Python be installed in the sandbox."
        )
