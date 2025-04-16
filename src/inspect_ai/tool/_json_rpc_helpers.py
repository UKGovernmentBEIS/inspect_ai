from typing import Literal

from pydantic import BaseModel, RootModel

from inspect_ai.tool._tool import ToolError


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


def parse_json_rpc_response(
    response_str: str,
    method: str,
    params: dict[str, object] | tuple[object, ...],
) -> object:
    """Validates the JSON RPC response and returns the result or raises a proper Inspect error."""
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCSuccessResponse(result=rpc_result):
            return rpc_result
        case JSONRPCError(code=code, message=message):
            raise exception_for_rpc_response_error(code, message, method, params)
        case _:
            raise ValueError(
                f"Unexpected JSON RPC response to request {_rpc_call_description(method, params)}: {response_str}"
            )


def exception_for_rpc_response_error(
    code: int,
    message: str,
    method: str | None = None,
    params: dict[str, object] | tuple[object, ...] | None = None,
) -> Exception:
    """Maps JSON-RPC error codes to Inspect tool related exceptions."""
    # code	    message	          meaning
    # -32000
    #    |      Server error	    Reserved for implementation-defined server-errors.
    # -32099
    # -32600	  Invalid Request	  The JSON sent is not a valid Request object.
    # -32601	  Method not found  The method does not exist / is not available.
    # -32602	  Invalid params	  Invalid method parameter(s).
    # -32603	  Internal error	  Internal JSON-RPC error.
    # -32700	  Parse error	      Invalid JSON was received by the server. An error occurred on the server while parsing the JSON text.

    if -32000 <= code >= -32099 or code == -32603:
        return ToolError(message)
    else:
        # -32600 (Invalid Request)
        #   If we sent a bogus request, it's 100% a code bug.
        # -32601 (Method not found)
        # -32602 (Invalid params)
        #   These shouldn't be possible since Inspect did validation prior to
        #   making the tool call. Because of that, these errors should not make
        #   it back to the model, so choose RuntimeError.
        # -32700 (Parse error)
        #   shouldn't be seen in this flow since we're processing responses, and
        #   this is a request oriented error.
        #
        return RuntimeError(
            f"Error executing tool command{f'  {_rpc_call_description(method, params)}' if method and params else ''}: {code=} {message}"
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
