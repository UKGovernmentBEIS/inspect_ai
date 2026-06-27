import json
import re
import traceback
from logging import getLogger
from pathlib import PurePosixPath
from textwrap import dedent
from typing import (
    Awaitable,
    Callable,
    Literal,
    cast,
    overload,
)

import anyio
from pydantic import JsonValue

from inspect_ai._util._async import coro_log_exceptions
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult

from .environment import SandboxEnvironment
from .limits import OutputLimitExceededError, override_max_exec_output_size

logger = getLogger(__name__)


REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
SERVICES_DIR = "/var/tmp/sandbox-services"
SERVICES_DIR_MODE = "1777"

ID = "id"
METHOD = "method"
PARAMS = "params"

ERROR = "error"
RESULT = "result"

POLLING_INTERVAL = 0.1

SERVICE_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
FILENAME_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
LIST_REQUESTS_SCRIPT = (
    'for request_file in "$1"/*.json; do '
    '[ -f "$request_file" ] && printf "%s\\0" "$request_file"; '
    "done"
)

# Output limit applied when reading a service request file. A service request
# payload (e.g. a model generate request carrying base64 images) can be far
# larger than a normal command's output, so we read it with a higher limit than
# the default exec output cap. 150 MiB is 3x the bridge proxy's 50 MiB request
# body cap -- 3x because the proxy re-serializes the body with ensure_ascii=True,
# which in the worst case triples the byte size of a non-ASCII body (a 2-byte
# UTF-8 char -> "\uXXXX" = 6 bytes; a non-BMP char -> a 12-byte surrogate pair).
# So this covers every request the proxy can accept.
SERVICE_REQUEST_READ_OUTPUT_LIMIT = 150 * 1024**2

SandboxServiceMethod = Callable[..., Awaitable[JsonValue]]


def _is_service_name(value: object) -> bool:
    return isinstance(value, str) and SERVICE_NAME_PATTERN.fullmatch(value) is not None


def _is_filename_token(value: object) -> bool:
    return (
        isinstance(value, str) and FILENAME_TOKEN_PATTERN.fullmatch(value) is not None
    )


@overload
async def sandbox_service(
    name: str,
    methods: list[SandboxServiceMethod] | dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment,
    user: str | None = ...,
    instance: str | None = ...,
    polling_interval: float | None = ...,
    started: anyio.Event | None = ...,
    requires_python: bool = ...,
    handle_requests: Literal[True] = ...,
) -> None: ...


@overload
async def sandbox_service(
    name: str,
    methods: list[SandboxServiceMethod] | dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment,
    user: str | None = ...,
    instance: str | None = ...,
    polling_interval: float | None = ...,
    started: anyio.Event | None = ...,
    requires_python: bool = ...,
    handle_requests: Literal[False] = ...,
) -> Callable[[], Awaitable[None]]: ...


async def sandbox_service(
    name: str,
    methods: list[SandboxServiceMethod] | dict[str, SandboxServiceMethod],
    until: Callable[[], bool],
    sandbox: SandboxEnvironment,
    user: str | None = None,
    instance: str | None = None,
    polling_interval: float | None = None,
    started: anyio.Event | None = None,
    requires_python: bool = True,
    handle_requests: bool = True,
) -> None | Callable[[], Awaitable[None]]:
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
        name: Service name (a bounded ASCII Python identifier).
        methods: Service methods.
        until: Function used to check whether the service should stop.
        sandbox: Sandbox to publish service to.
        user: User to login as. Defaults to the sandbox environment's default user.
        instance: If you want multiple instances of a service in a single sandbox
            then use the `instance` param (a bounded ASCII filename token).
        polling_interval: Polling interval for request checking. If not specified uses
            sandbox specific default (2 seconds if not specified, 0.2 seconds for Docker).
        started: Event to set when service has been started
        requires_python: Does the sandbox service require Python? Note that ALL sandbox services require Python unless they've injected an alternate implementation of the sandbox service client code.
        handle_requests: If `True` (the default), handle requests immediately -- will run so long as until() returns `True`. If `False`, returns an async function which can be called to handle requests.
    """
    # validate python in sandbox
    if requires_python:
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

    # function to handle requests catching errors and logging a warning
    # (catch broadly so an unexpected error reading the request queue can't
    # escape and tear down the polling loop)
    async def safe_handle_requests() -> None:
        try:
            await service.handle_requests()
        except Exception as ex:
            logger.warning(f"Error waiting for sandbox rpc: {ex}")

    # wait for and process methods
    if handle_requests:
        while not until():
            await anyio.sleep(polling_interval)
            await safe_handle_requests()
        return None
    else:
        return safe_handle_requests


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
            name (str): Service name (a bounded ASCII Python identifier).
            sandbox (SandboxEnvironment): Sandbox to publish service to.
            user (str | None): User to login as. Defaults to the sandbox environment's
              default user.
            instance: Unique identifier for an instance of this named service
               (a bounded ASCII filename token).
            started: Event to set when service has been started
        """
        if not _is_service_name(name):
            raise ValueError(
                f"invalid service name: {name!r} "
                "(must be a 1-128 character ASCII Python identifier)"
            )
        self._name = name
        self._sandbox = sandbox
        self._user = user
        self._started = started
        self._service_dir = PurePosixPath(SERVICES_DIR, self._name)
        self._root_service_dir = self._service_dir
        if instance is not None:
            if not _is_filename_token(instance):
                raise ValueError(
                    f"invalid instance: {instance!r} "
                    "(must be a 1-128 character ASCII filename token)"
                )
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
        # ensure shared parent exists with sticky-1777 perms and that
        # <service_dir> is owned by us (squat-check)
        await self._ensure_service_dir()

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
        result = await self._exec(
            [
                "sh",
                "-c",
                LIST_REQUESTS_SCRIPT,
                "sandbox-service-list",
                self._requests_dir,
            ]
        )

        # process requests
        if result.success:
            request_files = [file for file in result.stdout.split("\0") if file]
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
        request_path = PurePosixPath(request_file)
        requests_dir = PurePosixPath(self._requests_dir)
        if request_path.parent != requests_dir:
            logger.warning(
                f"Ignoring sandbox service request outside '{requests_dir}': "
                f"{request_file!r}"
            )
            return

        request_id = request_path.name.removesuffix(".json")
        if request_path.name != f"{request_id}.json" or not _is_filename_token(
            request_id
        ):
            logger.warning(
                "Discarding sandbox service request with invalid filename: "
                f"{request_file!r}"
            )
            await self._remove_request_file(request_file)
            return

        # read request -- raise the exec output limit for this read only, since a
        # service request payload can legitimately be much larger than a normal
        # command's output (see SERVICE_REQUEST_READ_OUTPUT_LIMIT).
        try:
            with override_max_exec_output_size(SERVICE_REQUEST_READ_OUTPUT_LIMIT):
                result = await self._exec(["cat", "--", request_file])
        except OutputLimitExceededError as ex:
            # Provider raised on overflow (e.g. k8s). The request is too large to
            # ever read, so it would otherwise sit in the queue and be retried (and
            # re-logged) on every poll forever while the client blocks. Discard it
            # and deliver an error response to unblock the client.
            await self._discard_unreadable_request(
                request_file,
                request_id,
                f"exceeded the {ex.limit_str} sandbox exec output limit",
            )
            return None
        if not result.success:
            raise RuntimeError(
                f"Error reading request '{request_file}' for service "
                f"{self._name}: {result.stderr}"
            )

        # parse request
        try:
            request_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # A decode error means either (a) the file is still being written --
            # retry on the next poll -- or (b) the provider silently TRUNCATED an
            # oversized read instead of raising (e.g. docker/local, whose service
            # execs bypass the output-size verifier), leaving a partial tail that
            # can never parse. Distinguish via the on-disk size: if the file
            # exceeds the read limit it can never be read, so discard it; otherwise
            # treat it as an incomplete write and retry.
            size = await self._request_size(request_file)
            if size is not None and size > SERVICE_REQUEST_READ_OUTPUT_LIMIT:
                limit_mib = SERVICE_REQUEST_READ_OUTPUT_LIMIT // 1024**2
                await self._discard_unreadable_request(
                    request_file,
                    request_id,
                    f"exceeds the {limit_mib} MiB service request read limit",
                )
            else:
                # log metadata only -- never the payload, which can be large and
                # may contain sensitive request content
                logger.warning(
                    "JSON decoding error reading service request "
                    f"'{request_file}' ({len(result.stdout)} chars read, on-disk "
                    f"size {size if size is not None else 'unknown'} bytes); "
                    "treating as an incomplete write and retrying."
                )
            return None
        if not isinstance(request_data, dict):
            await self._write_response(
                request_file,
                request_id,
                None,
                f"Service request is not a dict (type={type(request_data)})",
            )
            return None

        request_data_id = request_data.get(ID, None)
        if not _is_filename_token(request_data_id):
            await self._write_response(
                request_file,
                request_id,
                None,
                "Service request id is invalid",
            )
            return None
        if request_data_id != request_id:
            await self._write_response(
                request_file,
                request_id,
                None,
                "Service request id does not match request filename",
            )
            return None

        # read and validate params
        method_name = request_data.get(METHOD, None)
        params = request_data.get(PARAMS, None)
        if not isinstance(method_name, str):
            await self._write_response(
                request_file,
                request_id,
                None,
                f"Service {METHOD} not passed or not a string (type={type(method_name)})",
            )
        elif method_name not in self._methods:
            await self._write_response(
                request_file,
                request_id,
                None,
                f"Unknown method '{method_name}'",
            )
        elif not isinstance(params, dict):
            await self._write_response(
                request_file,
                request_id,
                None,
                f"{PARAMS} not passed or not a dict (type={params})",
            )

        # all clear, call the method
        else:
            from inspect_ai.log._samples import sample_active
            from inspect_ai.util._limit import LimitExceededError

            try:
                params = cast(dict[str, JsonValue], request_data.get(PARAMS))
                try:
                    method = self._methods[method_name]
                    await self._write_response(
                        request_file, request_id, await method(**params)
                    )
                except LimitExceededError as ex:
                    active = sample_active()
                    if active is not None:
                        active.limit_exceeded(ex)
                    await self._write_response(
                        request_file,
                        request_id,
                        None,
                        f"Limit exceeded calling method {method_name}: {ex.message}",
                    )
            except Exception as err:
                err_traceback = traceback.format_exc()
                await self._write_response(
                    request_file,
                    request_id,
                    None,
                    f"Error calling method {method_name}: {err}: {err_traceback}",
                )

    async def _write_response(
        self,
        request_file: str,
        request_id: str,
        result: JsonValue | None,
        error: str | None = None,
    ) -> None:
        response_data = {
            ID: request_id,
            RESULT: result,
            ERROR: error,
        }
        await self._write_text_file(
            self._response_path(request_id), json.dumps(response_data)
        )
        await self._remove_request_file(request_file)

    def _response_path(self, request_id: str) -> str:
        if not _is_filename_token(request_id):
            raise ValueError(f"invalid request id: {request_id!r}")
        return (PurePosixPath(self._responses_dir) / f"{request_id}.json").as_posix()

    async def _remove_request_file(self, request_file: str) -> None:
        request_path = PurePosixPath(request_file)
        if request_path.parent != PurePosixPath(self._requests_dir):
            raise ValueError(
                f"request file is outside request directory: {request_file}"
            )
        result = await self._exec(["rm", "-f", "--", request_file])
        if not result.success:
            raise RuntimeError(
                f"Error removing request file '{request_file}': {result.stderr}"
            )

    async def _request_size(self, request_file: str) -> int | None:
        """On-disk size of the request file in bytes (None if it can't be read).

        Used to tell an unreadable oversized request (which a provider may signal
        by silently truncating the read) apart from a still-being-written file.
        The size is read with a bounded command whose output is just a number, so
        it can't itself trip the output limit.
        """
        result = await self._exec(["wc", "-c", "--", request_file])
        if not result.success:
            return None
        try:
            return int(result.stdout.split(maxsplit=1)[0])
        except (IndexError, ValueError):
            return None

    async def _discard_unreadable_request(
        self, request_file: str, request_id: str, detail: str
    ) -> None:
        """Discard a request that can't be read and notify the client.

        Reading the full payload failed -- the provider either raised or silently
        truncated an oversized read. The validated filename identifies the client
        response, so no request payload needs to be parsed before the request is
        removed.
        """
        error = (
            f"Service '{self._name}' request payload could not be read "
            f"({detail}); the request was discarded."
        )
        logger.warning(f"{error} (request_file='{request_file}')")

        await self._write_response(request_file, request_id, None, error)

    async def _ensure_service_dir(self) -> None:
        # Make the shared parent 1777 so users other than the one that
        # created it can still place their service dirs inside. Run as
        # the sandbox default user (no user= override) since self._user
        # typically can't chmod a dir owned by someone else; best-effort
        # because even the default user may not own it.
        try:
            await self._sandbox.exec(
                [
                    "sh",
                    "-c",
                    f"mkdir -p {SERVICES_DIR} && "
                    f"chmod {SERVICES_DIR_MODE} {SERVICES_DIR} 2>/dev/null; true",
                ],
                timeout=600,
                concurrency=False,
            )
        except TimeoutError:
            raise RuntimeError(
                f"Timed out preparing shared services directory {SERVICES_DIR}"
            )

        service_dir = self._service_dir.as_posix()
        result = await self._exec(["mkdir", "-p", service_dir])
        if not result.success:
            # When the chmod above silently no-op'd, mkdir fails with a
            # generic Permission denied that blames the leaf. Re-blame
            # the parent if it's actually the unwritable one.
            parent = self._service_dir.parent.as_posix()
            writable = await self._exec(["test", "-w", parent])
            if not writable.success:
                user = self._user or "the sandbox default user"
                raise PrerequisiteError(
                    f"Sandbox service '{self._name}' cannot create "
                    f"'{service_dir}': its parent directory '{parent}' is "
                    f"not writable by user '{user}'. Another service may "
                    "have created it with restrictive permissions, or "
                    "claimed this name."
                )
            raise RuntimeError(
                f"Error creating service directory '{service_dir}' "
                f"for sandbox service '{self._name}': {result.stderr}"
            )

        # Squat check. test -O passes iff path is owned by the effective
        # uid; _exec runs as self._user, so this rejects dirs owned by
        # other users. With instance, also check the <name> parent.
        dirs_to_check = [service_dir]
        if self._service_dir != self._root_service_dir:
            dirs_to_check.append(self._root_service_dir.as_posix())
        for path in dirs_to_check:
            owned = await self._exec(["test", "-O", path])
            if not owned.success:
                user = self._user or "the sandbox default user"
                raise PrerequisiteError(
                    f"Sandbox service '{self._name}' cannot start: "
                    f"'{path}' exists but is not owned by user '{user}'. "
                    "Another service may have claimed this name."
                )

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
                cmd, user=self._user, input=input, timeout=600, concurrency=False
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
