"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the `inspect-tool-support` package code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

import json
from itertools import count
from textwrap import dedent
from typing import Literal, Type, TypeVar

from pydantic import BaseModel, RootModel

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.tool._tool import ToolError, ToolParsingError
from inspect_ai.util import sandbox_with
from inspect_ai.util._sandbox.environment import SandboxEnvironment


class JSONRPCResponseBase(BaseModel):
    jsonrpc: Literal["2.0"]
    id: int | float | str


class JSONRPCSuccessResponse(JSONRPCResponseBase):
    result: object


class JSONRPCError(BaseModel):
    """See: https://www.jsonrpc.org/specification#error_object"""

    code: int
    message: str
    data: object | None = None


class JSONRPCErrorResponse(JSONRPCResponseBase):
    error: JSONRPCError


class JSONRPCResponse(RootModel[JSONRPCSuccessResponse | JSONRPCErrorResponse]):
    pass


BaseModelT = TypeVar("BaseModelT", bound=BaseModel)
ScalarT = TypeVar("ScalarT", str, int, float, bool, None)

id_generator = count(666)


async def exec_scalar_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    result_type: Type[ScalarT],
    timeout: int | None = None,
    user: str | None = None,
) -> ScalarT:
    """
    Execute a JSON-RPC command to a sandbox environment expecting a scalar result.

    Args:
      sandbox (SandboxEnvironment): The sandbox environment to execute the command in.
      method (str): The JSON-RPC method to call.
      params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
      result_type (Type[ScalarT]): The scalar type (str, int, float, bool, None) to validate the result against.
      timeout (int | None, optional): The timeout for the execution. Defaults to None.
      user (str | None, optional): Optional username or UID to run the command as.

    Returns:
      ScalarT: The scalar result of the JSON-RPC call.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an error in the JSON-RPC response.
      ToolParsingError: If the JSON-RPC response contains a specific error code indicating a parsing error.
      ValueError: If the result is not of the expected scalar type.
    """
    rpc_result = await _exec_request(
        sandbox=sandbox,
        method=method,
        params=params,
        timeout=timeout,
        user=user,
    )
    if (result_type is type(None) and rpc_result is not None) or not isinstance(
        rpc_result, result_type
    ):
        raise ValueError(f"Expected {result_type} result, got {type(rpc_result)}")
    return rpc_result


async def exec_model_request(
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    result_type: Type[BaseModelT],
    timeout: int | None = None,
    user: str | None = None,
) -> BaseModelT:
    """
    Execute a JSON-RPC command to a sandbox environment expecting a model result.

    Args:
      sandbox (SandboxEnvironment): The sandbox environment to execute the command in.
      method (str): The JSON-RPC method to call.
      params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
      result_type (Type[BaseModelT]): The Pydantic model class to validate and parse the result.
      timeout (int | None, optional): The timeout for the execution. Defaults to None.
      user (str | None, optional): Optional username or UID to run the command as.

    Returns:
      BaseModelT: The parsed and validated result of the JSON-RPC call.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an error in the JSON-RPC response.
      ToolParsingError: If the JSON-RPC response contains a specific error code indicating a parsing error.
      ValueError: If the result cannot be validated against the provided model class.
    """
    rpc_result = await _exec_request(
        sandbox=sandbox,
        method=method,
        params=params,
        timeout=timeout,
        user=user,
    )
        return result_type.model_validate(rpc_result, strict=True)


async def exec_notification(
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    timeout: int | None = None,
    user: str | None = None,
) -> None:
    """
    Execute a JSON-RPC notification to a sandbox environment.

    A notification is a JSON-RPC request that doesn't expect any response.

    Args:
      sandbox (SandboxEnvironment): The sandbox environment to execute the notification in.
      method (str): The JSON-RPC method to call.
      params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
      timeout (int | None, optional): The timeout for the execution. Defaults to None.
      user (str | None, optional): Optional username or UID to run the command as.

    Returns:
      None: The function always returns None if successful.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an unexpected response to the notification.
    """
    stdout = await _exec_rpc(
        sandbox=sandbox,
        method=method,
        params=params,
        is_notification=True,
        timeout=timeout,
        user=user,
    )
    if stdout.strip():
        raise RuntimeError(
            f"Unexpected response to a Notification: {_rpc_call_description(method, params)}: {stdout}"
        )


async def _exec_request(
    *,
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    timeout: int | None = None,
    user: str | None = None,
) -> object:
    return _parse_json_rpc_response(
        await _exec_rpc(
            sandbox=sandbox,
            method=method,
            params=params,
            is_notification=False,
            timeout=timeout,
            user=user,
        ),
        method,
        params,
    )


async def _exec_rpc(
    *,
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    is_notification: bool,
    timeout: int | None = None,
    user: str | None = None,
) -> str:
    exec_result = await sandbox.exec(
        [SANDBOX_CLI, "exec"],
        input=_create_json_rpc_request(method, params, is_notification),
        timeout=timeout,
        user=user,
    )

    if not exec_result.success:
        raise RuntimeError(
            f"Sandbox.exec failure executing {_rpc_call_description(method, params)}: {exec_result.stderr}"
        )
    return exec_result.stdout


SANDBOX_CLI = "inspect-tool-support"
INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB = "aisiuk/inspect-tool-support"


async def tool_container_sandbox(
    tool_name: str, *, sandbox_name: str | None = None
) -> SandboxEnvironment:
    if sb := await sandbox_with(SANDBOX_CLI, True, name=sandbox_name):
        return sb

    # This sort of programmatic sentence building will not cut it if we ever
    # support other languages.
    raise PrerequisiteError(
        dedent(f"""
            The {tool_name} service was not found in {"any of the sandboxes" if sandbox_name is None else f"the sandbox '{sandbox_name}'"} for this sample. Please add the {tool_name} to your configuration.

            For example, the following Docker compose file uses the {INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB} reference image as its default sandbox:

            services:
              default:
                image: "{INSPECT_TOOL_SUPPORT_IMAGE_DOCKERHUB}"
                init: true

            Alternatively, you can include the service into your own Dockerfile:

            ENV PATH="$PATH:/opt/inspect_tool_support/bin"
            RUN python -m venv /opt/inspect_tool_support && \\
                /opt/inspect_tool_support/bin/pip install inspect-tool-support && \\
                /opt/inspect_tool_support/bin/inspect-tool-support post-install
            """).strip()
    )


def _create_json_rpc_request(
    method: str,
    params: dict[str, object] | tuple[object, ...],
    is_notification: bool,
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(params) if isinstance(params, tuple) else params,
            **({"id": next(id_generator)} if not is_notification else {}),
        }
    )


def _rpc_call_description(
    method: str, params: dict[str, object] | tuple[object, ...]
) -> str:
    """
    Generate a string description of an RPC call.

    Args:
        method (str): The name of the RPC method.
        params (dict[str, object] | tuple[object, ...]): The parameters for the RPC method.

    Returns:
        str: A string description of the RPC call.

    Examples:
        >>> _rpc_call_description("subtract", {"minuend": 42, "subtrahend": 23})
        'subtract(minuend: 42, subtrahend: 23)'

        >>> _rpc_call_description("subtract", (42, 23))
        'subtract(42, 23)'
    """
    normalized_params = (
        list(map(str, params))
        if isinstance(params, tuple)
        else [f"{k}: {v}" for k, v in params.items()]
    )
    return f"{method}({', '.join(normalized_params)})"


def _parse_json_rpc_response(
    response_str: str,
    method: str,
    params: dict[str, object] | tuple[object, ...],
) -> object:
    """Validates the JSON RPC response and returns the result or raises a proper Inspect error."""
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCSuccessResponse(result=rpc_result):
            return rpc_result
        case JSONRPCError(code=-32601 | -32602, message=message):
            raise ToolParsingError(message)
        # TODO: Fix this to use the whole range -32000 to -32099
        case JSONRPCError(code=-32000, message=message):
            raise ToolError(message)
        case JSONRPCError(code=code, message=message):
            raise RuntimeError(
                f"Error executing tool command {_rpc_call_description(method, params)}: {code=} {message}"
            )
        case _:
            raise ValueError(
                f"Unexpected JSON RPC response to request {_rpc_call_description(method, params)}: {response_str}"
            )
