import json
from itertools import count
from typing import Literal, Type, TypeVar

from pydantic import BaseModel, RootModel

from inspect_ai.tool._tool import ToolParsingError
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


id_generator = count(666)


async def exec_sandbox_rpc(
    sandbox: SandboxEnvironment,
    cmd_prefix: list[str],
    method: str,
    params: dict[str, object] | tuple[object, ...],
    result_cls: Type[BaseModelT],
    timeout: int | None = None,
) -> BaseModelT:
    request = _create_json_rpc_request(method, params)
    exec_result = await sandbox.exec(cmd_prefix + [request], timeout=timeout)

    # TODO: Verify this:
    # Since we're using JSON RPC, a non successful result from sanbox_env.exec() doesn't make
    # sense. We encode success/failure within the RPC response. It's weird to store it in two
    # places that have to agree.
    # confirm what happens when:
    #    !.success case
    #    the sandbox can't be found
    #    the RPC request is malformed
    #    the RPC returns an error like "element_id not found"

    if not exec_result.success:
        raise RuntimeError(
            f"Sandbox.exec failure executing {_rpc_call_description(method, params)}: {exec_result.stderr}"
        )

    match _parse_json_rpc_response(exec_result.stdout, result_cls):
        case JSONRPCError(-32601, message=message) | JSONRPCError(
            -32602, message=message
        ):
            raise ToolParsingError(message)
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


def _create_json_rpc_request(
    method: str, params: dict[str, object] | tuple[object, ...]
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": method,
            "id": next(id_generator),
            "params": list(params) if isinstance(params, tuple) else params,
        }
    )


def _rpc_call_description(
    method: str, params: dict[str, object] | tuple[object, ...]
) -> str:
    normalized_params = (
        list(map(str, params))
        if isinstance(params, tuple)
        else [f"{k}: {v}" for k, v in params.items()]
    )
    return f"{method}({', '.join(normalized_params)})"


def _parse_json_rpc_response(
    response_str: str,
    result_cls: Type[BaseModelT],
) -> BaseModelT | JSONRPCError:
    match JSONRPCResponse.model_validate_json(response_str).root:
        case JSONRPCErrorResponse(error=error):
            return error
        case JSONRPCSuccessResponse(result=rpc_result):
            return result_cls.model_validate(rpc_result, strict=True)
        case _:
            raise ValueError(f"Unexpected JSON RPC response: {response_str}")
