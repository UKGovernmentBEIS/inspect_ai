import json
from abc import ABC, abstractmethod
from itertools import count
from typing import Any, Literal, Protocol, Type, TypeAlias, TypeVar

from pydantic import BaseModel, RootModel


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
    """Protocol for JSON-RPC transport implementations.

    Defines the interface for transport mechanisms that handle the actual
    communication with JSON-RPC servers. Different implementations may use
    different underlying protocols (HTTP, Unix sockets, docker exec, etc.)
    but all must conform to this interface.

    The transport is responsible for:
    - Serializing the JSON-RPC request
    - Sending it via the appropriate communication channel
    - Receiving the response
    - Returning the raw response string for parsing

    Args:
        method: The JSON-RPC method name to call
        params: Parameters to pass to the method (list, dict, or None)
        is_notification: Whether this is a notification (no response expected)
        **transport_extra_args: Implementation-specific transport options
                              (e.g., timeout, authentication, etc.)

    Returns:
        The raw JSON-RPC response string from the server
    """

    async def __call__(
        self,
        method: str,
        params: JSONRPCParamsType,
        is_notification: bool,
        **transport_extra_args: Any,
    ) -> str: ...


class JSONRPCErrorMapper(ABC):
    """Abstract base for mapping JSON-RPC error codes to appropriate exceptions.

    Implementors provide domain-specific exception types for three categories
    of JSON-RPC errors. For example, a tool-layer implementation might map
    invalid_params to ToolParsingError and internal_error to ToolError so that
    those errors are fed back to the model rather than crashing the eval.

    All methods are static — implementations are stateless so there is no need
    to instantiate the mapper. Pass the *class* rather than an instance.
    """

    @staticmethod
    @abstractmethod
    def server_error(
        code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map a server-defined error code (-32000..-32099) to an exception."""
        ...

    @staticmethod
    @abstractmethod
    def invalid_params(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map a -32602 (Invalid params) error to an exception."""
        ...

    @staticmethod
    @abstractmethod
    def internal_error(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        """Map a -32603 (Internal error) error to an exception."""
        ...


class GenericJSONRPCErrorMapper(JSONRPCErrorMapper):
    """Default error mapper that uses standard Python exception types."""

    @staticmethod
    def server_error(
        code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del code, method, params
        return RuntimeError(message)

    @staticmethod
    def invalid_params(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return ValueError(message)

    @staticmethod
    def internal_error(
        message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        del method, params
        return RuntimeError(message)


async def exec_scalar_request(
    method: str,
    params: JSONRPCParamsType,
    result_type: Type[ScalarT],
    transport: JSONRPCTransport,
    error_mapper: type[JSONRPCErrorMapper],
    **transport_extra_args: Any,
) -> ScalarT:
    """
    Execute a JSON-RPC command expecting a scalar result.

    Args:
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      result_type (Type[ScalarT]): The scalar type (str, int, float, bool, None) to validate the result against.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.
      error_mapper (JSONRPCErrorMapper): Maps JSON-RPC error codes to appropriate exceptions.
      **transport_extra_args: Additional arguments passed to the transport (e.g. timeout, user).

    Returns:
      ScalarT: The scalar result of the JSON-RPC call.

    Raises:
      RuntimeError: If execution fails or if there is an error in the JSON-RPC response.
      ValueError: If the result is not of the expected scalar type.
    """
    rpc_result = await _exec_request(
        method=method,
        params=params,
        transport=transport,
        error_mapper=error_mapper,
        **transport_extra_args,
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
    error_mapper: type[JSONRPCErrorMapper],
    **transport_extra_args: Any,
) -> BaseModelT:
    """
    Execute a JSON-RPC command to a sandbox environment expecting a model result.

    Args:
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      result_type (Type[BaseModelT]): The Pydantic model class to validate and parse the result.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.
      error_mapper (JSONRPCErrorMapper): Maps JSON-RPC error codes to appropriate exceptions.
      **transport_extra_args: Additional arguments passed to the transport (e.g. timeout, user).

    Returns:
      BaseModelT: The parsed and validated result of the JSON-RPC call.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an error in the JSON-RPC response.
      ValueError: If the result cannot be validated against the provided model class.
    """
    rpc_result = await _exec_request(
        method=method,
        params=params,
        transport=transport,
        error_mapper=error_mapper,
        **transport_extra_args,
    )
    return result_type.model_validate(rpc_result, strict=True)


async def exec_notification(
    method: str,
    params: JSONRPCParamsType,
    transport: JSONRPCTransport,
    **transport_extra_args: Any,
) -> None:
    """
    Execute a JSON-RPC notification to a sandbox environment.

    A notification is a JSON-RPC request that doesn't expect any response.

    Args:
      method (str): The JSON-RPC method to call.
      params (JSONRPCParamsType): The parameters for the JSON-RPC method.
      transport (JSONRPCTransport): The transport callable to use for the RPC communication.
      **transport_extra_args: Additional arguments passed to the transport (e.g. timeout, user).

    Returns:
      None: The function always returns None if successful.

    Raises:
      RuntimeError: If the sandbox execution fails or if there is an unexpected response to the notification.
    """
    stdout = await transport(
        method=method,
        params=params,
        is_notification=True,
        **transport_extra_args,
    )
    if stdout.strip():
        raise RuntimeError(
            f"Unexpected response to a Notification: {rpc_call_description(method, params)}: {stdout}"
        )


async def _exec_request(
    *,
    method: str,
    params: JSONRPCParamsType,
    transport: JSONRPCTransport,
    error_mapper: type[JSONRPCErrorMapper],
    **transport_extra_args: Any,
) -> object:
    """Execute a request using the provided transport mechanism."""
    return parse_json_rpc_response(
        await transport(
            method=method,
            params=params,
            is_notification=False,
            **transport_extra_args,
        ),
        method,
        params,
        error_mapper,
    )


def parse_json_rpc_response(
    response_str: str,
    method: str,
    params: JSONRPCParamsType,
    error_mapper: type[JSONRPCErrorMapper],
) -> object:
    """Validates the JSON RPC response and returns the result or raises a proper Inspect error."""
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCSuccessResponse(result=rpc_result):
            return rpc_result
        case JSONRPCErrorResponse(error=JSONRPCError(code=code, message=message)):
            raise exception_for_rpc_response_error(
                code, message, method, params, error_mapper
            )
        case _:
            raise ValueError(
                f"Unexpected JSON RPC response to request {rpc_call_description(method, params)}: {response_str}"
            )


def exception_for_rpc_response_error(
    code: int,
    message: str,
    method: str,
    params: JSONRPCParamsType,
    error_mapper: type[JSONRPCErrorMapper],
) -> Exception:
    """Maps JSON-RPC error codes to exceptions via the provided error mapper."""
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
        return error_mapper.server_error(code, message, method, params)
    elif code == -32602:
        return error_mapper.invalid_params(message, method, params)
    elif code == -32603:
        return error_mapper.internal_error(message, method, params)
    else:
        # -32600 (Invalid Request)
        #   If we sent a bogus request, it's 100% a code bug.
        # -32601 (Method not found)
        # -32700 (Parse error)
        #   shouldn't be seen in this flow since we're processing responses, and
        #   this is a request oriented error.
        #
        return RuntimeError(
            f"Error executing tool command{f'  {rpc_call_description(method, params)}' if method and params else ''}: {code=} {message}"
        )


def rpc_call_description(method: str, params: JSONRPCParamsType) -> str:
    """
    Generate a string description of an RPC call.

    Args:
        method (str): The name of the RPC method.
        params (JSONRPCParamsType): The parameters for the RPC method.

    Returns:
        str: A string description of the RPC call.

    Examples:
        >>> rpc_call_description("subtract", {"minuend": 42, "subtrahend": 23})
        'subtract(minuend: 42, subtrahend: 23)'

        >>> rpc_call_description("subtract", (42, 23))
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
