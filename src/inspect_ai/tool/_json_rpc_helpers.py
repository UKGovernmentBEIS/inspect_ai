import json
from itertools import count
from typing import Literal, Protocol, Type, TypeAlias, TypeVar

from pydantic import BaseModel, RootModel

from inspect_ai.tool._tool import ToolError, ToolParsingError


class JSONRPCResponseBase(BaseModel):
    jsonrpc: Literal["2.0"]
    id: int | float | str


class JSONRPCSuccessResponse(JSONRPCResponseBase):
    result: object


JSONRPCParamsType: TypeAlias = list[object] | dict[str, object] | None


class JSONRPCIncoming(BaseModel):
    jsonrpc: Literal["2.0"]
    method: str
    params: JSONRPCParamsType = None


class JSONRPCRequest(JSONRPCIncoming):
    id: int | float | str


class JSONRPCNotification(JSONRPCIncoming):
    pass


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


class JSONRPCTransport(Protocol):
    async def __call__(
        self, method: str, params: JSONRPCParamsType, is_notification: bool
    ) -> str: ...


class JSONRPCServerErrorMapper(Protocol):
    def __call__(
        self, code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception: ...


async def exec_scalar_request(
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[ScalarT],
    transport: JSONRPCTransport,
    server_error_mapper: JSONRPCServerErrorMapper,
) -> ScalarT:
    """
    Execute a JSON-RPC command expecting a scalar result.

    Args:
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      result_type (Type[ScalarT]): The scalar type (str, int, float, bool, None) to validate the result against.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.
      server_error_mapper (JSONRPCServerErrorMapper): A callable to map server specific JSON-RPC errors to exceptions.

    Returns:
      ScalarT: The scalar result of the JSON-RPC call.

    Raises:
      RuntimeError: If execution fails or if there is an error in the JSON-RPC response.
      ToolParsingError: If the JSON-RPC response contains a specific error code indicating a parsing error.
      ValueError: If the result is not of the expected scalar type.
    """
    rpc_result = await _exec_request(
        method=method,
        params=params,
        transport=transport,
        server_error_mapper=server_error_mapper,
    )
    if (result_type is type(None) and rpc_result is not None) or not isinstance(
        rpc_result, result_type
    ):
        raise ValueError(f"Expected {result_type} result, got {type(rpc_result)}")
    return rpc_result


async def exec_model_request(
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[BaseModelT],
    transport: JSONRPCTransport,
    server_error_mapper: JSONRPCServerErrorMapper | None = None,
) -> BaseModelT:
    """
    Execute a JSON-RPC command to a sandbox environment expecting a model result.

    Args:
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      result_type (Type[BaseModelT]): The Pydantic model class to validate and parse the result.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.
      server_error_mapper (JSONRPCServerErrorMapper): A callable to map server specific JSON-RPC errors to exceptions.

    Returns:
      BaseModelT: The parsed and validated result of the JSON-RPC call.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an error in the JSON-RPC response.
      ToolParsingError: If the JSON-RPC response contains a specific error code indicating a parsing error.
      ValueError: If the result cannot be validated against the provided model class.
    """
    rpc_result = await _exec_request(
        method=method,
        params=params,
        transport=transport,
        server_error_mapper=server_error_mapper,
    )
    return result_type.model_validate(rpc_result, strict=True)


async def exec_notification(
    method: str,
    params: JSONRPCParamsType,
    transport: JSONRPCTransport,
) -> None:
    """
    Execute a JSON-RPC notification to a sandbox environment.

    A notification is a JSON-RPC request that doesn't expect any response.

    Args:
      sandbox (SandboxEnvironment): The sandbox environment to execute the notification in.
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.

    Returns:
      None: The function always returns None if successful.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an unexpected response to the notification.
    """
    stdout = await transport(
        method=method,
        params=params,
        is_notification=True,
    )
    if stdout.strip():
        raise RuntimeError(
            f"Unexpected response to a Notification: {_rpc_call_description(method, params)}: {stdout}"
        )


async def _exec_request(
    *,
    method: str,
    params: JSONRPCParamsType,
    transport: JSONRPCTransport,
    server_error_mapper: JSONRPCServerErrorMapper | None = None,
) -> object:
    """Execute a request using the provided transport mechanism."""
    return parse_json_rpc_response(
        await transport(
            method=method,
            params=params,
            is_notification=False,
        ),
        method,
        params,
        server_error_mapper,
    )


def parse_json_rpc_response(
    response_str: str,
    method: str,
    params: JSONRPCParamsType,
    server_error_mapper: JSONRPCServerErrorMapper | None = None,
) -> object:
    """Validates the JSON RPC response and returns the result or raises a proper Inspect error."""
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCSuccessResponse(result=rpc_result):
            return rpc_result
        case JSONRPCErrorResponse(error=JSONRPCError(code=code, message=message)):
            raise exception_for_rpc_response_error(
                code, message, method, params, server_error_mapper
            )
        case _:
            raise ValueError(
                f"Unexpected JSON RPC response to request {_rpc_call_description(method, params)}: {response_str}"
            )


def exception_for_rpc_response_error(
    code: int,
    message: str,
    method: str,
    params: JSONRPCParamsType,
    server_error_mapper: JSONRPCServerErrorMapper | None = None,
) -> Exception:
    """Maps JSON-RPC error codes to Inspect tool related exceptions."""
    # code    message           meaning
    # -32000
    #    |    Server error      Reserved for implementation-defined server-errors.
    # -32099
    # -32600  Invalid Request   The JSON sent is not a valid Request object.
    # -32601  Method not found  The method does not exist / is not available.
    # -32602  Invalid params    Invalid method parameter(s).
    # -32603  Internal error    Internal JSON-RPC error.
    # -32700  Parse error       Invalid JSON was received by the server. An error occurred on the server while parsing the JSON text.

    if -32099 <= code <= -32000:
        # This range is server defined. This layer has no idea what server was
        # called, so if special mapping is needed, it must be provided by the
        # caller.
        return (
            server_error_mapper(code, message, method, params)
            if server_error_mapper
            else ToolError(message)
        )
    elif code == -32602:  # (Invalid params)
        # Even though the Inspect side does validation, it can't possibly be
        # complete - especially for tools that have dynamic action dependant
        # rules for optional/required params.
        return ToolParsingError(message)
    elif code == -32603:
        return ToolError(message)
    else:
        # -32600 (Invalid Request)
        #   If we sent a bogus request, it's 100% a code bug.
        # -32601 (Method not found)
        # -32700 (Parse error)
        #   shouldn't be seen in this flow since we're processing responses, and
        #   this is a request oriented error.
        #
        return RuntimeError(
            f"Error executing tool command{f'  {_rpc_call_description(method, params)}' if method and params else ''}: {code=} {message}"
        )


def _rpc_call_description(method: str, params: JSONRPCParamsType) -> str:
    """
    Generate a string description of an RPC call.

    Args:
        method (str): The name of the RPC method.
        params (JSONRPCParamsType): The parameters for the RPC method.

    Returns:
        str: A string description of the RPC call.

    Examples:
        >>> _rpc_call_description("subtract", {"minuend": 42, "subtrahend": 23})
        'subtract(minuend: 42, subtrahend: 23)'

        >>> _rpc_call_description("subtract", (42, 23))
        'subtract(42, 23)'
    """
    normalized_params = (
        ""
        if params is None
        else list(map(str, params))
        if isinstance(params, list)
        else [f"{k}: {v}" for k, v in params.items()]
    )
    return f"{method}({', '.join(normalized_params)})"


id_generator = count(666)


def create_json_rpc_request(
    method: str,
    params: JSONRPCParamsType,
    is_notification: bool,
) -> str:
    return json.dumps(
        remove_none_values(
            {
                "jsonrpc": "2.0",
                "method": method,
                **({"params": params} if params else {}),
                **({"id": next(id_generator)} if not is_notification else {}),
            }
        )
    )


def remove_none_values(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: remove_none_values(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [remove_none_values(item) for item in obj if item is not None]
    return obj
