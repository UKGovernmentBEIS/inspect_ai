"""
This module provides helper code for handling JSON-RPC communication between the inspect process and the `inspect-tool-support` package code running in the sandbox environment.

It includes definitions for JSON-RPC request and response models, as well as functions to create and parse JSON-RPC requests and responses.
"""

import json
from itertools import count
from textwrap import dedent
from typing import Literal, Type, TypeVar, cast

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
StrOrIntOrModelTOrNone = TypeVar(
    "StrOrIntOrModelTOrNone", bound=str | int | BaseModel | None
)

id_generator = count(666)


async def exec_sandbox_rpc(
    sandbox: SandboxEnvironment,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    result_cls: Type[StrOrIntOrModelTOrNone],
    timeout: int | None = None,
    user: str | None = None,
    is_notification: bool = False,
) -> StrOrIntOrModelTOrNone:
    """
    Execute a JSON-RPC command to a sandbox environment.

    Note that the JSON RPC request is sent to the exec'ed program via stdin.

    Args:
      sandbox (SandboxEnvironment): The sandbox environment to execute the command in.
      method (str): The JSON-RPC method to call.
      params (dict[str, object] | tuple[object, ...]): The parameters for the JSON-RPC method.
      result_cls (Type[BaseModelT]): The class to use for parsing the result.
      timeout (int | None, optional): The timeout for the execution. Defaults to None.
      user: Optional username or UID to run the command as.

    Returns:
      BaseModelT: The parsed result of the JSON-RPC call.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an error in the JSON-RPC response.
      ToolParsingError: If the JSON-RPC response contains a specific error code indicating a parsing error.
    """
    req = _create_json_rpc_request(method, params, is_notification)
    exec_result = await sandbox.exec(
        [SANDBOX_CLI, "exec"],
        input=req,
        timeout=timeout,
        user=user,
    )

    if not exec_result.success:
        raise RuntimeError(
            f"Sandbox.exec failure executing {_rpc_call_description(method, params)}: {exec_result.stderr}"
        )

    if is_notification:
        if exec_result.stdout.strip():
            raise RuntimeError(
                f"Notification sent a response {_rpc_call_description(method, params)}: {exec_result.stdout}"
            )
        return cast(StrOrIntOrModelTOrNone, None)
    else:
        match _parse_json_rpc_response(exec_result.stdout, result_cls):
            case JSONRPCError(code=-32601 | -32602, message=message):
                raise ToolParsingError(message)
            case JSONRPCError(code=-32000, message=message):
                raise ToolError(message)
            case JSONRPCError(code=code, message=message):
                raise RuntimeError(
                    f"Error executing tool command {_rpc_call_description(method, params)}: {code=} {message}"
                )
            # case result_cls() as model: yields a mypy error since it has narrowed model down
            # to BaseModel and not BaseModelT. ???
            case model if isinstance(model, result_cls):
                return model
            case not_possible:
                raise RuntimeError(
                    f"Error executing tool command {_rpc_call_description(method, params)}: {not_possible}"
                )


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
    result_cls: Type[StrOrIntOrModelTOrNone],
) -> StrOrIntOrModelTOrNone | JSONRPCError:
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCErrorResponse(error=error):
            return error
        case JSONRPCSuccessResponse(result=rpc_result):
            # TODO: Wow. Is there really no way to convince Python to narrow these types
            # and avoid the cast's
            if result_cls is str:
                if not isinstance(rpc_result, str):
                    raise ValueError(f"Expected string result, got {type(rpc_result)}")
                return cast(StrOrIntOrModelTOrNone, rpc_result)
            elif result_cls is int:
                if not isinstance(rpc_result, int):
                    raise ValueError(f"Expected int result, got {type(rpc_result)}")
                return cast(StrOrIntOrModelTOrNone, rpc_result)
            elif result_cls is type(None):
                if rpc_result is not None:
                    raise ValueError(f"Expected None result, got {type(rpc_result)}")
                return cast(StrOrIntOrModelTOrNone, rpc_result)
            else:
                return cast(
                    StrOrIntOrModelTOrNone,
                    cast(BaseModel, result_cls).model_validate(rpc_result, strict=True),
                )
        case _:
            raise ValueError(f"Unexpected JSON RPC response: {response_str}")
